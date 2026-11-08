"""A Wix Stores shop, read from the JSON its gallery pages embed.

Fixtures under `fixtures/wix/` are real gallery pages and a products sitemap from
the November 2026 survey of a Wix shop, trimmed to a few products and anonymised
(`shop-w.test`, made-up ids, images and SKUs). Nothing here reaches the network:
an `httpx.MockTransport` serves them, robots.txt included.

Covered:
  - the fields a gallery gives, and the title rule (name vs image alt text);
  - `comparePrice` is the sale price, not an old one;
  - out of stock, and the brand default;
  - `?page=N` is cumulative, so page 2 repeats page 1 and adds the rest;
  - a merchandising gallery and the sitemap pass never clear a category;
  - the sitemap pass creates nothing, and reports a product no gallery showed;
  - robots.txt is consulted for every request, and the requests are counted.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import StockSignal
from makhzan_schemas.models import Category, Listing, Source
from sqlalchemy import select
from worker import robots as robots_mod
from worker.pipeline import run_source
from worker.robots import DisallowedByRobots, RobotsCache
from worker.sources.base import SupplierInfo
from worker.sources.registry import build_adapter
from worker.sources.wix import (
    SITEMAP_PARTITION,
    WixStoresAdapter,
    gallery_category,
    sitemap_slugs,
)

FIXTURES = Path(__file__).parent / "fixtures" / "wix"
BASE = "https://www.shop-w.test"
SUPPLIER = SupplierInfo(slug="shop-w", name="Shop W")
CROSSWALK = {"PLA+": ("electronics", "filament")}

BLACK = "00000000-0000-0000-0000-00000000a000"  # on PLA+ and New Arrival
GOLD = "00000000-0000-0000-0000-00000000a004"  # out of stock
LIGHT_BROWN = "00000000-0000-0000-0000-00000000a008"  # no SKU; only on page 2
ASA = "00000000-0000-0000-0000-00000000a00e"  # on sale, out of stock, New Arrival only
MATTE = "00000000-0000-0000-0000-00000000a011"  # on sale, New Arrival only


def _read(name: str) -> str:
    return (FIXTURES / name).read_text()


def _wix(**options) -> WixStoresAdapter:
    options.setdefault("galleries", ["/shop-2"])
    options.setdefault("tag_galleries", ["/shop"])
    options.setdefault("brand", "Acme")
    options.setdefault("categories", CROSSWALK)
    options.setdefault("polite_delay", 0)
    return WixStoresAdapter("shop-w", BASE, SUPPLIER, **options)


class Shop:
    """A fake Wix host: every request it receives, and the pages it serves."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str | None], str] = {
            ("/robots.txt", None): _read("robots.txt"),
            ("/shop", None): _read("gallery_new_arrival.html"),
            ("/shop-2", None): _read("gallery_pla.html"),
            ("/shop-2", "2"): _read("gallery_pla_page2.html"),
            ("/store-products-sitemap.xml", None): _read("store-products-sitemap.xml"),
        }
        self.requests: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = urlsplit(str(request.url))
        self.requests.append(url.path + (f"?{url.query}" if url.query else ""))
        page = parse_qs(url.query).get("page", [None])[0]
        body = self.routes.get((url.path, page))
        if body is None:
            return httpx.Response(404, text="")
        return httpx.Response(200, text=body)

    def pages(self) -> list[str]:
        """Requests to the shop itself, robots.txt aside."""
        return [r for r in self.requests if r != "/robots.txt"]


@pytest.fixture
def shop(monkeypatch):
    fake = Shop()
    real = httpx.AsyncClient

    def client(**kwargs):
        return real(transport=httpx.MockTransport(fake.handle), **kwargs)

    # One door for everything: the adapter's client and robots.txt's both.
    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(robots_mod, "ROBOTS", RobotsCache())
    return fake


async def _gallery_items(adapter, path="/shop-2"):
    first = await adapter.fetch_page(path, 1)
    second = await adapter.fetch_page(path, 2) if first.has_more else None
    items = first.items + (second.items if second else [])
    return {raw.external_id: raw for raw in items}


# --------------------------------------------------------------------------- #
# One product
# --------------------------------------------------------------------------- #


async def test_a_gallery_product_becomes_a_listing(shop):
    items = await _gallery_items(_wix())
    raw = items[BLACK]
    norm = _wix().normalize(raw)

    # The name is "Black PLA +"; the alt text says what it is and who made it.
    assert raw.title == "Acme Black PLA+ 3D printer filament"
    assert norm.price == Decimal("695")
    assert norm.currency == "EGP"
    assert norm.stock_signal == StockSignal.IN_STOCK
    assert raw.source_url == f"{BASE}/product-page/black-pla"
    assert raw.category_hint == "PLA+"
    # Full size: the stored file, not the 500 px transform the page shows.
    assert raw.images and all(
        url.startswith("https://static.wixstatic.com/media/a1b2c3_") and "/v1/" not in url
        for url in raw.images
    )
    assert len(raw.images) == len(set(raw.images)) == 5


async def test_the_sku_is_an_attribute_never_a_part_number(shop):
    raw = (await _gallery_items(_wix()))[BLACK]
    norm = _wix().normalize(raw)
    assert norm.attributes["sku"] == "W-002-1-4"
    assert norm.part_number is None
    assert "sku" not in (await _gallery_items(_wix()))[LIGHT_BROWN].raw


async def test_stock_counts_and_options_are_not_kept(shop):
    """Counts read 0 or negative in a gallery while the product page says 38,
    and options promise sizes no variant exists for."""
    raw = (await _gallery_items(_wix()))[BLACK]
    assert set(raw.raw) <= {"platform", "category", "sku", "compare_at_price"}


async def test_compare_price_is_the_sale_price(shop):
    """Wix's naming is inverted: `price` 1000 is the list price and
    `comparePrice` 900 is what the buyer pays."""
    items = await _gallery_items(_wix(), "/shop")
    assert items[ASA].price_text == "900"
    assert items[ASA].raw["compare_at_price"] == "1000"
    assert items[MATTE].price_text == "725"
    # Zero means "not on sale", not a price of nothing.
    assert items[BLACK].price_text == "695"
    assert "compare_at_price" not in items[BLACK].raw


async def test_out_of_stock_is_read_from_the_gallery(shop):
    items = await _gallery_items(_wix())
    assert _wix().normalize(items[GOLD]).stock_signal == StockSignal.OUT_OF_STOCK
    asa = (await _gallery_items(_wix(), "/shop"))[ASA]
    assert _wix().normalize(asa).stock_signal == StockSignal.OUT_OF_STOCK
    assert asa.price_text == "900", "out of stock still has its price"


async def test_the_brand_default_applies_when_a_product_names_none(shop):
    items = await _gallery_items(_wix())
    assert {raw.brand for raw in items.values()} == {"Acme"}
    assert {raw.brand for raw in (await _gallery_items(_wix(brand=None))).values()} == {None}


def test_a_product_naming_its_own_brand_keeps_it():
    product = {"id": "p1", "urlPart": "p1", "name": "Spool", "price": 10, "brand": "Other"}
    assert _wix()._to_raw(product, None).brand == "Other"


@pytest.mark.parametrize(
    ("name", "alt", "expected"),
    [
        ("ASA", "Acme ASA 3D printer filament", "Acme ASA 3D printer filament"),
        ("PLA MATTE", "Acme Matte PLA 3D printer filament", "Acme Matte PLA 3D printer filament"),
        # The alt text says nothing of the name: a caption or a file name.
        ("Red PLA", "IMG_2041.jpg", "Red PLA"),
        ("Red PLA", "Acme Blue PLA filament", "Red PLA"),
        ("Cold White  PLA+", "", "Cold White PLA+"),
    ],
)
def test_the_alt_text_titles_a_product_only_when_it_contains_the_name(name, alt, expected):
    product = {"id": "p1", "urlPart": "p1", "name": name, "media": [{"altText": alt}]}
    assert _wix()._to_raw(product, None).title == expected


# --------------------------------------------------------------------------- #
# Paging: ?page=N is cumulative
# --------------------------------------------------------------------------- #


async def test_page_two_repeats_page_one_and_only_the_rest_is_emitted(shop):
    adapter = _wix()
    first = await adapter.fetch_page("/shop-2", 1)
    assert len(first.items) == 3 and first.has_more

    second = await adapter.fetch_page("/shop-2", 2)
    # The page lists all 5, the first 3 again among them; only 2 are new.
    assert (
        len(gallery_category(_read("gallery_pla_page2.html"))["productsWithMetaData"]["list"]) == 5
    )
    assert {raw.external_id for raw in second.items} == {
        LIGHT_BROWN,
        "00000000-0000-0000-0000-00000000a00a",
    }
    assert not second.has_more, "the list reached totalCount"
    assert shop.pages() == ["/shop-2", "/shop-2?page=2"]


async def test_a_resumed_gallery_emits_its_whole_cumulative_page(shop):
    """A run that resumes at page 2 never saw page 1, and page 2 has it all."""
    second = await _wix().fetch_page("/shop-2", 2)
    assert len(second.items) == 5 and not second.has_more


async def test_a_page_that_does_not_grow_ends_the_gallery(shop):
    """A shop that ignores ?page would otherwise be asked for page 3, 4, 5..."""
    shop.routes[("/shop-2", "2")] = _read("gallery_pla.html")
    adapter = _wix()
    await adapter.fetch_page("/shop-2", 1)
    second = await adapter.fetch_page("/shop-2", 2)
    assert second.items == [] and not second.has_more


async def test_a_page_without_the_store_data_is_an_error_not_an_empty_gallery(shop):
    """Read as empty, a redesigned page would archive the whole shop."""
    shop.routes[("/shop-2", None)] = "<html><body>Maintenance</body></html>"
    with pytest.raises(ValueError, match="wix-warmup-data"):
        await _wix().fetch_page("/shop-2", 1)


# --------------------------------------------------------------------------- #
# Partitions, categories and the sitemap
# --------------------------------------------------------------------------- #


def test_merchandising_first_then_types_then_the_sitemap():
    assert _wix(galleries=["/a", "/b"], tag_galleries=["/new"]).partitions() == [
        "/new",
        "/a",
        "/b",
        SITEMAP_PARTITION,
    ]
    assert _wix(sitemap=None).partitions() == ["/shop", "/shop-2"]


@pytest.mark.parametrize("path", ["shop", "/shop?lightbox=1", "/shop#top"])
def test_a_gallery_is_a_plain_path(path):
    with pytest.raises(ValueError, match="plain path"):
        _wix(galleries=[path])


async def test_only_a_type_gallery_knows_the_category(shop):
    adapter = _wix()
    typed = (await _gallery_items(adapter))[BLACK]
    tagged = (await _gallery_items(adapter, "/shop"))[BLACK]

    assert adapter.knows_category(typed) and adapter.category_for(typed) == CROSSWALK["PLA+"]
    assert adapter.source_categories(typed) == ["PLA+"]
    # "New Arrival" is not a type: no category, no drift entry, and not a
    # pass that may clear what PLA+ set.
    assert not adapter.knows_category(tagged)
    assert adapter.category_for(tagged) is None
    assert adapter.source_categories(tagged) == []


async def test_the_sitemap_pass_creates_nothing(shop):
    """It has an address and an image per product, but no id, price or stock."""
    adapter = _wix()
    page = await adapter.fetch_page(SITEMAP_PARTITION, 1)
    assert page.items == [] and not page.has_more


def test_sitemap_slugs_skip_image_urls():
    slugs = sitemap_slugs(_read("store-products-sitemap.xml"))
    assert slugs[0] == "black-pla" and "discontinued-spool" in slugs
    assert len(slugs) == 8 and not any("wixstatic" in s for s in slugs)


async def test_a_full_run(shop):
    """The whole source in one run: what it stores, what it reports, what it costs."""
    adapter = _wix()
    run = await run_source(adapter.source_id, adapter)

    async with SessionLocal() as session:
        rows = (await session.execute(select(Listing))).scalars().all()
        filament = (
            await session.execute(select(Category).where(Category.slug == "filament"))
        ).scalar_one()
    listings = {row.external_id: row for row in rows}
    # 5 PLA+ and 2 only on New Arrival; Black, on both, is stored once.
    assert len(listings) == 7
    assert run.items_seen == 8
    # Every request the host received: /shop, /shop-2 twice, the sitemap.
    assert run.stats["requests"] == {"pages": 4}
    assert shop.pages() == [
        "/shop",
        "/shop-2",
        "/shop-2?page=2",
        "/store-products-sitemap.xml",
    ]
    assert shop.requests.count("/robots.txt") == 1

    # Black was categorized by PLA+ and the New Arrival pass did not clear it;
    # ASA, on New Arrival only, was placed by its (alt text) title.
    assert listings[BLACK].category_id == filament.id
    assert listings[ASA].category_id == filament.id
    assert listings[ASA].brand == "Acme"

    report = run.stats["source_report"]
    assert report["only_in_sitemap"] == ["discontinued-spool"]
    assert "discontinued-spool" in report["warnings"][0]
    assert "crosswalk" not in run.stats or "New Arrival" not in str(run.stats["crosswalk"])


async def test_a_new_arrival_pass_does_not_clear_a_category(shop):
    """The second run sweeps only New Arrival, where the title gives inference
    nothing to go on: the category PLA+ set stays."""
    adapter = _wix()
    await run_source(adapter.source_id, adapter)
    shop.routes[("/shop", None)] = (
        shop.routes[("/shop", None)]
        .replace('"name":"Black PLA +"', '"name":"Black Spool"')
        .replace("Acme Black PLA+ 3D printer filament", "Acme Black Spool")
    )
    later = _wix()
    later.partitions = lambda: ["/shop"]  # only the merchandising pass
    await run_source(later.source_id, later, limit=50)
    async with SessionLocal() as session:
        black = (
            await session.execute(select(Listing).where(Listing.external_id == BLACK))
        ).scalar_one()
    assert black.category_id is not None


async def test_the_sitemap_is_not_compared_against_galleries_another_run_swept(shop):
    """A gallery swept on an earlier day would make every product on it look missing."""
    adapter = _wix()
    await adapter.fetch_page("/shop", 1)
    await adapter.fetch_page(SITEMAP_PARTITION, 1)
    report = adapter.run_report()
    assert "only_in_sitemap" not in report
    assert "/shop-2" in report["sitemap_not_compared"]


# --------------------------------------------------------------------------- #
# Politeness
# --------------------------------------------------------------------------- #


async def test_robots_txt_is_read_and_obeyed(shop):
    shop.routes[("/robots.txt", None)] = "User-agent: *\nDisallow: /shop-2\n"
    with pytest.raises(DisallowedByRobots):
        await _wix().fetch_page("/shop-2", 1)
    assert shop.pages() == [], "nothing robots.txt forbids was requested"


async def test_the_shops_real_robots_file_allows_what_the_adapter_asks_for(shop):
    """Wix's own file forbids `?lightbox=`, which a gallery's links can carry."""
    rules = robots_mod.Rules(_read("robots.txt"))
    agent = "Mozilla/5.0 Chrome/153.0.0.0"
    assert not rules.allowed(f"{BASE}/shop?lightbox=dataItem-1", agent)
    for path in ["/shop", "/shop-2?page=2", "/store-products-sitemap.xml"]:
        assert rules.allowed(f"{BASE}{path}", agent)
    assert rules.crawl_delay(agent) is None


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def test_the_registry_builds_it_from_a_sources_row():
    row = Source(
        source_id="shop-w",
        adapter="wix",
        base_url=BASE,
        supplier={"slug": "shop-w", "name": "Shop W"},
        config={"galleries": ["/shop-2"], "tag_galleries": ["/shop"], "brand": "Acme"},
    )
    adapter = build_adapter(row)
    assert isinstance(adapter, WixStoresAdapter)
    assert adapter.partitions() == ["/shop", "/shop-2", SITEMAP_PARTITION]
    assert adapter.brand == "Acme"
    assert adapter.authoritative_categories is False


def test_an_unknown_key_is_refused():
    with pytest.raises(TypeError):
        _wix(product_pages=True)
