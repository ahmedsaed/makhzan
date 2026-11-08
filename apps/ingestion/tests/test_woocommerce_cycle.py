"""What a WooCommerce shop publishes beyond its product pages, and what it costs.

Fixtures under `fixtures/woocommerce/` are real Store API and WordPress REST
responses from the November 2026 discovery survey, trimmed to a few rows and
anonymised (shops A–C, `*.test` domains). Nothing here reaches the network: an
`httpx.MockTransport` serves them, and robots.txt is stubbed to allow.

Covered:
  - "contact for price" is `price_on_request` with no price, never 0;
  - minimum order and purchase multiples are kept beside the per-piece price;
  - a manufacturer part number stated in the shop's own table is kept, and fills
    the brand, but is not handed to grouping;
  - boilerplate sections are stripped before description and specs are read;
  - what a part fits is read from options and (on request) titles;
  - a stock count only where the shop's counts are public;
  - variants, the shop's breadcrumb and quantity breaks from once-a-cycle data,
    fetched once per cycle — not once per run — and counted in the run's stats;
  - a shop whose Store API hides out-of-stock products keeps them, out of
    stock, instead of archiving them at the end of the cycle.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ListingStatus, SourceType, StockSignal
from makhzan_schemas.models import Listing, Source, Supplier
from sqlalchemy import select
from worker import http as http_mod
from worker.contact import contact_from_html
from worker.http import CycleFetcher
from worker.pipeline import run_source
from worker.robots import ROBOTS
from worker.sources import woocommerce as woo_mod
from worker.sources.base import SupplierInfo
from worker.sources.woocommerce import UNLISTED_OUT_OF_STOCK, WooCommerceAdapter

FIXTURES = Path(__file__).parent / "fixtures" / "woocommerce"
BASE = "https://shop-c.test"
SUPPLIER = SupplierInfo(slug="shop-c", name="Shop C")


def _load(name: str):
    return json.loads((FIXTURES / name).read_text())


def _by_id(name: str, product_id: int) -> dict:
    return next(row for row in _load(name) if row["id"] == product_id)


def _woo(**options) -> WooCommerceAdapter:
    options.setdefault("polite_delay", 0)
    return WooCommerceAdapter("shop-c", BASE, SUPPLIER, **options)


async def _no_pause() -> float:
    return 0.0


class Shop:
    """A fake WooCommerce host: path -> handler(params) -> (body, headers)."""

    def __init__(self) -> None:
        self.routes: dict[str, object] = {}
        self.requests: list[tuple[str, dict]] = []

    def serve(self, path: str, handler) -> None:
        self.routes[path] = handler

    def _handle(self, request: httpx.Request) -> httpx.Response:
        url = urlsplit(str(request.url))
        params = {k: v[0] for k, v in parse_qs(url.query).items()}
        self.requests.append((url.path, params))
        handler = self.routes.get(url.path)
        if handler is None:
            return httpx.Response(404, json={"code": "rest_no_route"})
        body, headers = handler(params)
        if isinstance(body, str):
            return httpx.Response(200, text=body, headers=headers)
        return httpx.Response(200, json=body, headers=headers)

    def client(self, **kwargs) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self._handle), **kwargs)

    def count(self, path: str) -> int:
        return sum(1 for p, _ in self.requests if p == path)


def _paged(rows: list, per_page: int = 100):
    """A WordPress collection: the page asked for, and how many there are."""

    def handler(params):
        size = int(params.get("per_page", per_page))
        page = int(params.get("page", 1))
        pages = max(1, -(-len(rows) // size))
        return rows[(page - 1) * size : page * size], {"X-WP-TotalPages": str(pages)}

    return handler


@pytest.fixture
def shop(monkeypatch):
    fake = Shop()

    async def allowed(url, user_agent):
        return True

    async def no_delay(url, user_agent):
        return None

    monkeypatch.setattr(ROBOTS, "allowed", allowed)
    monkeypatch.setattr(ROBOTS, "crawl_delay", no_delay)
    monkeypatch.setattr(http_mod, "make_client", fake.client)
    monkeypatch.setattr(woo_mod, "make_client", fake.client)
    return fake


# --------------------------------------------------------------------------- #
# From the product row alone (no extra requests)
# --------------------------------------------------------------------------- #


def test_contact_for_price_is_price_on_request_never_zero():
    """Unpurchasable at "0": the shop sells it but will not price it online."""
    product = _by_id("shop_c_products.json", 31094)
    assert product["is_purchasable"] is False and product["prices"]["price"] == "0"

    raw = _woo()._to_raw(product, "in stock")
    norm = _woo().normalize(raw)

    assert raw.raw["price_on_request"] is True
    assert raw.price_text is None
    assert norm.price is None


def test_a_priced_product_is_not_on_request():
    raw = _woo()._to_raw(_by_id("shop_c_products.json", 33501), "in stock")
    assert "price_on_request" not in raw.raw
    assert raw.price_text is not None


def test_minimum_order_and_multiple_are_kept_beside_the_per_piece_price():
    """Priced per piece, sold in tens: both facts, and the price stays per piece."""
    raw = _woo()._to_raw(_load("shop_a_products.json")[0], "in stock")
    assert raw.raw["min_quantity"] == 10
    assert raw.raw["multiple_of"] == 10
    assert raw.price_text == "0.25"


def test_quantity_rules_of_one_are_not_written():
    product = _by_id("shop_c_products.json", 33501)
    product["add_to_cart"].update(minimum=1, multiple_of=1)
    raw = _woo()._to_raw(product, "in stock")
    assert "min_quantity" not in raw.raw and "multiple_of" not in raw.raw


def test_a_stated_manufacturer_part_number_is_kept_but_not_grouped_on():
    raw = _woo()._to_raw(_load("shop_a_products.json")[0], "in stock")
    assert raw.raw["mfr_part_number"] == "FRC1206J561 TS"
    # The shop names no brand of its own, so its table's manufacturer fills it.
    assert raw.brand == "FOJAN"
    # Grouping reads `part_number`; the stated MPN is not fed to it in this change.
    assert raw.part_number is None


def test_the_shops_own_brand_wins_over_its_table():
    product = _load("shop_a_products.json")[0]
    product["brands"] = [{"name": "Acme"}]
    assert _woo()._to_raw(product, "in stock").brand == "Acme"


def test_boilerplate_sections_are_stripped_before_reading():
    product = _load("shop_b_products.json")[0]
    sections = ["Why Buy from Widget Works?", "Ordering, Delivery and Support"]

    kept = _woo()._to_raw(product, "in stock")
    stripped = _woo(strip_description_sections=sections)._to_raw(product, "in stock")

    assert "Why Buy from Widget Works?" in kept.description
    assert "Why Buy" not in stripped.description
    assert "Ordering, Delivery" not in stripped.description
    assert "Every order is checked" not in stripped.description
    # The product's own sections, before and after the boilerplate, survive.
    assert "Key Features" in stripped.description
    assert "Package Includes" in stripped.description
    assert stripped.raw["specs"]["Isolation voltage"] == "5000V RMS"
    assert stripped.raw["specs"]["Package"] == "DIP-4, through-hole"


def test_what_a_part_fits_comes_from_its_compatibility_option():
    raw = _woo()._to_raw(_by_id("shop_c_products.json", 31298), "in stock")
    assert raw.raw["compatible_with"] == ["X1 Series/P1 Series/A1", "A1 mini"]


def test_what_a_part_fits_comes_from_its_title_only_when_asked():
    product = _by_id("shop_c_products.json", 31094)
    assert "compatible_with" not in _woo()._to_raw(product, "in stock").raw
    raw = _woo(compatibility_from_titles=True)._to_raw(product, "in stock")
    assert raw.raw["compatible_with"] == ["Neptune 4 Plus / 4 Max"]


@pytest.mark.parametrize(
    "title",
    [
        "Norton Resin for Casting jewelry 500g",
        "PC4-01 Pneumatic Connector For 1.75mm",
        "T Slot Nuts for Aluminum Profile",
        "Dagu 4WD Smart Robot Car Chassis Kit for Arduino",
    ],
)
def test_a_for_phrase_that_names_no_machine_is_not_a_fit(title):
    product = _by_id("shop_c_products.json", 31094)
    product["name"] = title
    raw = _woo(compatibility_from_titles=True)._to_raw(product, "in stock")
    assert "compatible_with" not in raw.raw


def test_a_purchase_limit_is_a_stock_count_only_where_counts_are_public():
    """The shop's page says "In Stock"; the 4 is only its purchase limit."""
    product = _by_id("shop_c_products.json", 33501)
    assert product["add_to_cart"]["maximum"] == 4

    assert "stock_quantity" not in _woo()._to_raw(product, "in stock").raw
    raw = _woo(stock_from_purchase_limit=True)._to_raw(product, "in stock")
    assert raw.raw["stock_quantity"] == 4


@pytest.mark.parametrize("maximum,sold_individually", [(9999, False), (1, True)])
def test_no_limit_or_one_per_order_is_not_a_count(maximum, sold_individually):
    product = _by_id("shop_c_products.json", 33501)
    product["add_to_cart"]["maximum"] = maximum
    product["sold_individually"] = sold_individually
    raw = _woo(stock_from_purchase_limit=True)._to_raw(product, "in stock")
    assert "stock_quantity" not in raw.raw


# --------------------------------------------------------------------------- #
# Once-a-cycle reference data
# --------------------------------------------------------------------------- #


async def test_variants_are_attached_to_their_parent(shop, monkeypatch):
    rows = _load("shop_c_variations.json")
    # Two pages, so paging follows X-WP-TotalPages rather than stopping early.
    monkeypatch.setattr(woo_mod, "PER_PAGE", 4)
    shop.serve("/wp-json/wc/store/v1/products", _paged(rows))
    adapter = _woo()
    fetcher = CycleFetcher(_no_pause)

    data = await adapter.fetch_cycle_part(fetcher, "variations")
    adapter.use_cycle_data({"variations": data})

    assert fetcher.requests["variations"] == 2
    assert all(p == {"type": "variation", "per_page": "4", "page": str(n)}
               for n, (_, p) in enumerate(shop.requests, 1))  # fmt: skip
    raw = adapter._to_raw(_by_id("shop_c_products.json", 31298), "in stock")
    variants = raw.raw["variants"]
    assert len(variants) == len(rows) == raw.raw["variant_count"]
    first = variants[0]
    assert set(first) <= {"title", "price", "in_stock", "stock_quantity", "sku"}
    assert isinstance(first["price"], float) and first["price"] > 0
    assert first["in_stock"] is True
    assert ":" not in first["title"]  # "Compatibility: A1 mini" reads "A1 mini"
    # One listing per parent: its price stays the cheapest, as the Store API says.
    assert float(raw.price_text) == min(v["price"] for v in variants)


def test_an_option_label_keeps_commas_inside_a_value():
    label = woo_mod._option_label("Flow Type: High Flow, Type: X2D , P2S , H2C (Left), Size: 0.8mm")
    assert label == "High Flow / X2D , P2S , H2C (Left) / 0.8mm"


async def test_the_shops_breadcrumb_comes_from_its_category_tree(shop):
    shop.serve("/wp-json/wc/store/v1/products/categories", _paged(_load("shop_c_categories.json")))
    adapter = _woo()
    adapter.use_cycle_data(
        {"categories": await adapter.fetch_cycle_part(CycleFetcher(_no_pause), "categories")}
    )
    raw = adapter._to_raw(_by_id("shop_c_products.json", 31094), "in stock")
    # The deepest of its categories, root first, unescaped.
    assert raw.raw["shop_category_path"] == ["ELEGOO", "Spare Parts & Accessories"]


async def test_quantity_breaks_come_from_the_wordpress_route(shop):
    shop.serve("/wp-json/wp/v2/product", _paged(_load("shop_b_wp_tiers.json")))
    adapter = _woo(price_breaks=True)
    data = await adapter.fetch_cycle_part(CycleFetcher(_no_pause), "price_breaks")
    # Only products with rules are kept.
    assert set(data) == {"18721", "18770"}
    assert "tiered_pricing_fixed_rules" in shop.requests[0][1]["_fields"]
    adapter.use_cycle_data({"price_breaks": data})

    product = _by_id("shop_c_products.json", 33501)
    product.update(
        id=18770, prices={**product["prices"], "price": "8500", "currency_minor_unit": 2}
    )
    raw = adapter._to_raw(product, "in stock")
    assert raw.raw["price_breaks"] == [
        {"min_quantity": 20, "price": 80.0},
        {"min_quantity": 50, "price": 75.0},
        {"min_quantity": 100, "price": 70.0},
        {"min_quantity": 200, "price": 65.0},
    ]
    assert raw.price_text == "85.00"  # the single-unit price is untouched


def test_a_percentage_break_is_priced_from_the_listing():
    adapter = _woo(price_breaks=True)
    adapter.use_cycle_data({"price_breaks": {"5": {"type": "percentage", "rules": {"10": 10}}}})
    product = _by_id("shop_c_products.json", 33501)
    product.update(id=5, prices={**product["prices"], "price": "200", "currency_minor_unit": 0})
    assert adapter._to_raw(product, "in stock").raw["price_breaks"] == [
        {"min_quantity": 10, "price": 180.0}
    ]


def test_reference_data_is_ignored_when_its_switch_is_off():
    adapter = _woo(variations=False, category_tree=False)
    adapter.use_cycle_data(
        {"variations": {"31298": [{"title": "x", "price": 1.0, "in_stock": True}]},
         "categories": {"1096": ["ELEGOO", 0]}}
    )  # fmt: skip
    raw = adapter._to_raw(_by_id("shop_c_products.json", 31298), "in stock")
    assert "variants" not in raw.raw and "shop_category_path" not in raw.raw


def test_cheap_parts_are_on_by_default_and_price_breaks_are_not():
    assert _woo().cycle_data_parts() == ["categories", "variations", "contact"]
    assert "price_breaks" in _woo(price_breaks=True).cycle_data_parts()
    assert _woo(variations=False, category_tree=False, contact=False).cycle_data_parts() == []


# --------------------------------------------------------------------------- #
# The shop's contact details
# --------------------------------------------------------------------------- #


def _page(*blocks: dict, body: str = "") -> str:
    scripts = "".join(
        f'<script type="application/ld+json">{json.dumps(b, ensure_ascii=False)}</script>'
        for b in blocks
    )
    return f"<html><head>{scripts}</head><body>{body}</body></html>"


_STORE = {
    "@context": "https://schema.org",
    "@graph": [
        {"@type": "WebSite", "name": "Shop"},
        {
            "@type": ["ElectronicsStore", "Organization"],
            "name": "Shop",
            "email": "info@shop.test",
            "telephone": "+20-2-0000-0000",
            "openingHours": ["Sa,Su,Mo,Tu,We,Th 10:00-20:30", "Fr 14:00-20:00"],
            "address": {
                "@type": "PostalAddress",
                "streetAddress": "12 Example St., Mall Wing",
                "addressLocality": "Nasr City",
                "addressRegion": "Cairo",
                "addressCountry": "EG",
            },
        },
    ],
}


def test_contact_is_read_from_the_shops_json_ld():
    contact = contact_from_html(_page(_STORE), "https://shop.test/")
    assert contact["address"] == "12 Example St., Mall Wing"
    assert contact["area"] == "Nasr City"
    assert contact["governorate"] == "Cairo"
    assert contact["phone"] == "+20-2-0000-0000"
    assert contact["email"] == "info@shop.test"
    assert contact["opening_hours"] == ["Sa,Su,Mo,Tu,We,Th 10:00-20:30", "Fr 14:00-20:00"]
    assert contact["source_url"] == "https://shop.test/"
    assert contact["fetched_at"]


def test_an_address_one_slot_off_is_put_back_and_kept_in_its_language():
    """Number as street, street as locality, district as region, city as country."""
    block = {
        "@type": ["ElectronicsStore", "Organization"],
        "telephone": "01000000000",
        "address": {
            "streetAddress": "31",
            "addressLocality": "شارع المثال",
            "addressRegion": "حي المثال",
            "addressCountry": "القاهرة",
        },
    }
    contact = contact_from_html(_page(block), "https://shop.test/")
    assert contact["address"] == "31 شارع المثال"
    assert contact["area"] == "حي المثال"
    assert contact["governorate"] == "القاهرة"


def test_whatsapp_is_kept_only_when_the_page_names_one_number():
    one = (
        '<a href="https://wa.me/201000000001">chat</a><a href="https://wa.me/201000000001?text=hi">'
    )
    share = '<a href="https://api.whatsapp.com/send?text=https%3A%2F%2Fshop.test">share</a>'
    two = one + '<a href="https://api.whatsapp.com/send?phone=201000000002">branch</a>'

    assert contact_from_html(_page(_STORE, body=one + share), "u")["whatsapp"] == "+201000000001"
    assert "whatsapp" not in contact_from_html(_page(_STORE, body=two), "u")


def test_an_organization_with_only_a_logo_is_no_contact():
    bare = {"@type": "Organization", "name": "Shop", "logo": "https://shop.test/logo.png"}
    assert contact_from_html(_page(bare), "u") is None
    # ...but the page's own phone link still is one, when it names one number.
    body = '<a href="tel:01000000003">call</a><a href="tel:+201000000003">call</a>'
    assert contact_from_html(_page(bare, body=body), "u")["phone"] == "01000000003"


def test_an_organization_with_an_address_and_a_contact_point_counts():
    block = {
        "@type": "Organization",
        "address": {"streetAddress": "8 Example St.", "addressLocality": "Shubra",
                    "addressRegion": "Cairo", "addressCountry": "مصر"},
        "contactPoint": [{"@type": "ContactPoint", "telephone": "+20 100 000 0004"}],
    }  # fmt: skip
    contact = contact_from_html(_page(block), "u")
    assert contact["phone"] == "+20 100 000 0004"
    assert contact["governorate"] == "Cairo"


# --------------------------------------------------------------------------- #
# Through the pipeline
# --------------------------------------------------------------------------- #


def _store_api(shop: Shop, by_status: dict[str, list]) -> None:
    def handler(params):
        if params.get("type") == "variation":
            return _load("shop_c_variations.json"), {"X-WP-TotalPages": "1"}
        rows = by_status.get(params.get("stock_status"), [])
        return (rows if params.get("page") == "1" else []), {}

    shop.serve("/wp-json/wc/store/v1/products", handler)
    shop.serve("/wp-json/wc/store/v1/products/categories", _paged(_load("shop_c_categories.json")))
    shop.serve("/", lambda params: (_page(_STORE), {}))


async def _seed_source(adapter: WooCommerceAdapter) -> None:
    async with SessionLocal() as session:
        session.add(
            Source(
                source_id=adapter.source_id,
                adapter="woocommerce",
                base_url=BASE,
                supplier={"slug": SUPPLIER.slug, "name": SUPPLIER.name},
                config={},
            )
        )
        await session.commit()


async def _listing(external_id: str) -> Listing:
    async with SessionLocal() as session:
        return (
            await session.execute(select(Listing).where(Listing.external_id == external_id))
        ).scalar_one()


async def test_reference_data_is_fetched_once_a_cycle_and_counted(shop):
    products = _load("shop_c_products.json")
    _store_api(shop, {"instock": products})
    # One page a run: the cycle (3 statuses, 2 pages each) spans two runs.
    adapter = _woo(max_partitions_per_run=2)
    await _seed_source(adapter)

    first = await run_source(adapter.source_id, adapter)
    assert first.stats["requests"] == {"pages": 3, "categories": 1, "variations": 1, "contact": 1}
    second = await run_source(adapter.source_id, _woo(max_partitions_per_run=2))
    assert second.stats.get("cycle"), "the second run closes the cycle"
    # Mid-cycle: read from the source's row, not fetched again.
    assert second.stats["requests"] == {"pages": 1}
    assert shop.count("/wp-json/wc/store/v1/products/categories") == 1

    # The variable product carries its variants, and the shop its contact details.
    listing = await _listing("31298")
    assert len(listing.attributes["variants"]) == 6
    assert listing.attributes["shop_category_path"] == ["3D Printing", "Spare Parts & Accessories"]
    async with SessionLocal() as session:
        supplier = (await session.execute(select(Supplier))).scalar_one()
        assert supplier.contact["governorate"] == "Cairo"
        source = (await session.execute(select(Source))).scalar_one()
        assert set(source.cycle_data) == {"categories", "variations", "contact"}

    # A new cycle fetches it afresh.
    third = await run_source(adapter.source_id, _woo(max_partitions_per_run=2))
    assert third.stats["requests"]["variations"] == 1


async def test_a_failed_part_is_reported_and_the_sweep_goes_on(shop):
    _store_api(shop, {"instock": _load("shop_c_products.json")})
    shop.routes.pop("/wp-json/wc/store/v1/products/categories")  # now a 404

    run = await run_source("shop-c", _woo())

    assert any("cycle data categories" in e for e in run.stats["errors"])
    assert run.items_seen == 3
    assert "shop_category_path" not in (await _listing("31094")).attributes


async def test_a_limited_run_stores_no_reference_data(shop):
    _store_api(shop, {"instock": _load("shop_c_products.json")})
    adapter = _woo()
    await _seed_source(adapter)

    await run_source(adapter.source_id, adapter, limit=2)

    async with SessionLocal() as session:
        assert (await session.execute(select(Source))).scalar_one().cycle_data is None
        assert (await session.execute(select(Supplier))).scalar_one().contact is None


async def test_a_hidden_out_of_stock_product_is_kept_not_archived(shop):
    """A1: the Store API leaves out-of-stock products out entirely.

    First cycle: both products in stock. Second cycle: the Store API returns
    neither; the WordPress route still lists one, marked out of stock. That one
    stays listed, out of stock. The other has gone from both, and is archived.
    """
    products = [_by_id("shop_c_products.json", 33501), _by_id("shop_c_products.json", 31298)]
    wp_rows = _load("shop_c_wp_products.json")
    gone = {"id": 33501, "class_list": ["post-33501", "product", "outofstock"]}
    options = dict(hides_out_of_stock=True, variations=False, category_tree=False, contact=False)

    _store_api(shop, {"instock": products})
    shop.serve("/wp-json/wp/v2/product", _paged(wp_rows))
    first = await run_source("shop-c", _woo(**options))
    assert UNLISTED_OUT_OF_STOCK in _woo(**options).partitions()
    assert first.stats.get("cycle")
    assert (await _listing("33501")).stock_signal == StockSignal.IN_STOCK

    _store_api(shop, {"instock": []})
    shop.serve("/wp-json/wp/v2/product", _paged([gone, *wp_rows]))
    second = await run_source("shop-c", _woo(**options))

    kept = await _listing("33501")
    assert kept.status == ListingStatus.ACTIVE
    assert kept.stock_signal == StockSignal.OUT_OF_STOCK
    assert kept.title_en, "what was stored stays: the WordPress route carries no details"
    assert (await _listing("31298")).status == ListingStatus.ARCHIVED
    assert second.stats["archived"] == 1
    # The fixture's own out-of-stock product (32647) was never stored: not created.
    assert second.stats["out_of_stock_unlisted"] == {"kept": 1, "unknown": 1}
    assert shop.requests[-1][1]["_fields"] == "id,class_list"


async def test_without_the_setting_a_hidden_product_is_archived(shop):
    """The behaviour A1 fixes, pinned so the setting is seen to be what changes it."""
    options = dict(variations=False, category_tree=False, contact=False)
    _store_api(shop, {"instock": [_by_id("shop_c_products.json", 33501)]})
    await run_source("shop-c", _woo(**options))
    _store_api(shop, {"instock": []})
    await run_source("shop-c", _woo(**options))

    assert (await _listing("33501")).status == ListingStatus.ARCHIVED


async def test_the_unlisted_pass_restores_a_listing_an_earlier_cycle_archived(shop):
    options = dict(hides_out_of_stock=True, variations=False, category_tree=False, contact=False)
    _store_api(shop, {"instock": [_by_id("shop_c_products.json", 33501)]})
    shop.serve("/wp-json/wp/v2/product", _paged([]))
    await run_source("shop-c", _woo(**options))
    async with SessionLocal() as session:
        listing = (await session.execute(select(Listing))).scalar_one()
        listing.status = ListingStatus.ARCHIVED
        await session.commit()

    _store_api(shop, {"instock": []})
    shop.serve("/wp-json/wp/v2/product", _paged([{"id": 33501, "class_list": ["outofstock"]}]))
    await run_source("shop-c", _woo(**options))

    listing = await _listing("33501")
    assert listing.status == ListingStatus.ACTIVE
    assert listing.stock_signal == StockSignal.OUT_OF_STOCK


def test_source_type_is_unchanged():
    assert _woo().source_type == SourceType.SCRAPED
