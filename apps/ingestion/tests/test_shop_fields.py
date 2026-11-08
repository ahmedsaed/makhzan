"""Fields a shop already publishes in what the crawler downloads.

Videos and datasheets in a Shopify description, the publication date, variants in
the shared shape, the collections a product is in, and an Odoo card's change
token. The fixtures are trimmed from real catalogue responses (the shop's name
replaced); nothing here goes to the network.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from selectolax.parser import HTMLParser

from worker import http as http_mod
from worker import robots as robots_mod
from worker.richtext import documents_from_html, video_url, videos_from_html
from worker.sources import shopify as shopify_mod
from worker.sources.base import SupplierInfo
from worker.sources.odoo import OdooAdapter
from worker.sources.shopify import ShopifyAdapter

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://shop.volta-parts.test"
VOLTA = SupplierInfo(slug="volta-parts", name="Volta Parts Egypt")
#: Saved before any test swaps httpx.AsyncClient for the robots fetch.
_RealClient = httpx.AsyncClient


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


PRODUCTS = {p["title"]: p for p in _load("shopify_products.json")["products"]}


def _product(prefix: str) -> dict:
    return next(p for title, p in PRODUCTS.items() if title.startswith(prefix))


def _adapter(**kw) -> ShopifyAdapter:
    return ShopifyAdapter("volta-parts", BASE, VOLTA, **kw)


# --------------------------------------------------------------------------- #
# Videos
# --------------------------------------------------------------------------- #


def test_an_embed_titled_after_the_player_is_labelled_video():
    raw = _adapter()._to_raw(_product("R20C"))
    assert raw.raw["videos"] == [
        {"label": "Video", "url": "https://www.youtube.com/watch?v=Asa48p0D1aI"}
    ]


def test_protocol_relative_embeds_become_https():
    raw = _adapter()._to_raw(_product("L293D"))
    assert raw.raw["videos"] == [
        {"label": "Video", "url": "https://www.youtube.com/watch?v=zKq0ebA3C04"}
    ]
    vimeo = _adapter()._to_raw(_product("GT2 Closed"))
    assert vimeo.raw["videos"] == [{"label": "Video", "url": "https://vimeo.com/40914530"}]


def test_linked_videos_keep_their_link_text_and_embeds_are_counted_once():
    videos = _adapter()._to_raw(_product("TMC2208")).raw["videos"]
    urls = [v["url"] for v in videos]
    assert len(urls) == len(set(urls))
    assert {
        "label": "TMC2208 Three way of control, part one: legacy mode",
        "url": "https://www.youtube.com/watch?v=TubpTMFkbVs",
    } in videos
    assert all(v["url"].startswith("https://") for v in videos)


def test_a_product_without_videos_records_none():
    assert "videos" not in _adapter()._to_raw(_product("74HC07")).raw


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        ("https://youtu.be/zKq0ebA3C04?t=3", "https://www.youtube.com/watch?v=zKq0ebA3C04"),
        (
            "https://www.youtube-nocookie.com/embed/zKq0ebA3C04",
            "https://www.youtube.com/watch?v=zKq0ebA3C04",
        ),
        (
            "https://www.youtube.com/watch?v=zKq0ebA3C04&t=30",
            "https://www.youtube.com/watch?v=zKq0ebA3C04",
        ),
        ("https://vimeo.com/40914530", "https://vimeo.com/40914530"),
        # Not one video: a channel, a playlist, the shop's own mp4, a script.
        ("https://www.youtube.com/@someshop", None),
        ("https://www.youtube.com/playlist?list=PL123", None),
        ("https://cdn.shopify.com/videos/c/o/v/abc.mp4", None),
        ("javascript:alert(1)", None),
        ("https://vimeo.com/channels/staffpicks", None),
    ],
)
def test_video_urls_are_canonical(href, expected):
    assert video_url(href) == expected


def test_a_video_link_in_the_description_text_is_not_dropped_from_the_text():
    """Videos are added to attributes; the description is untouched."""
    raw = _adapter()._to_raw(_product("TMC2208"))
    assert raw.description and "TMC2208" in raw.description


def test_videos_are_capped():
    html = "".join(f'<a href="https://youtu.be/abcdefghi{i:02d}">v</a>' for i in range(30))
    assert len(videos_from_html(html)) == 10


# --------------------------------------------------------------------------- #
# Datasheets
# --------------------------------------------------------------------------- #


def test_a_datasheet_archive_page_is_a_document():
    """Over the whole catalogue every ".pdf" link was already caught; the only
    datasheets missed were pages of a datasheet archive."""
    docs = _adapter()._to_raw(_product("74HC07")).raw["documents"]
    assert docs == [
        {
            "label": "Click Here",
            "url": "http://www.alldatasheet.com/datasheet-pdf/pdf/23210/STMICROELECTRONICS/74HC07.html?",
        }
    ]


def test_pdf_links_are_still_documents():
    docs = _adapter()._to_raw(_product("L293D")).raw["documents"]
    assert [d["url"] for d in docs] == [
        "https://cdn.shopify.com/s/files/1/0000/0001/files/l293d.pdf?575"
    ]


@pytest.mark.parametrize(
    "href",
    [
        "https://www.alldatasheet.com/",  # the archive's home page is not a datasheet
        "https://www.st.com/en/logic/74hc07.html",  # a maker's product page
        "https://github.com/someone/project",
    ],
)
def test_other_pages_are_not_documents(href):
    assert documents_from_html(f'<a href="{href}">Datasheet</a>', BASE) == []


# --------------------------------------------------------------------------- #
# Publication date and variants
# --------------------------------------------------------------------------- #


def test_published_at_is_the_shops_date_and_updated_at_is_ignored():
    product = _product("R20C")
    assert product["published_at"].startswith("2024-08-30T16:34:12+03:00")
    raw = _adapter()._to_raw(product)
    assert raw.raw["published_at"] == "2024-08-30"
    assert "updated_at" not in raw.raw


def test_an_unreadable_publication_date_is_left_out():
    raw = _adapter()._to_raw({**_product("R20C"), "published_at": "yesterday"})
    assert "published_at" not in raw.raw


def test_variants_take_the_shared_shape():
    product = {
        **_product("R20C"),
        "options": [{"name": "Color", "values": ["White", "Black"]}],
        "variants": [
            {"title": "White", "price": "840.00", "sku": "PLAWHT", "available": True},
            {
                "title": "Black",
                "price": "860.00",
                "sku": "",
                "available": False,
                "compare_at_price": "900.00",
            },
        ],
    }
    assert _adapter()._to_raw(product).raw["variants"] == [
        {"title": "White", "price": "840.00", "in_stock": True, "sku": "PLAWHT"},
        {"title": "Black", "price": "860.00", "in_stock": False},
    ]


# --------------------------------------------------------------------------- #
# Collections
# --------------------------------------------------------------------------- #

ROBOTS_TXT = "User-agent: *\nDisallow: /collections/*+*\nDisallow: /cart\n"


class _Shop:
    """A fake storefront: the collection list, one collection, and the feed."""

    def __init__(self, extra_collections=()):
        self.sent: list[str] = []
        self.collections = _load("shopify_collections.json")["collections"] + list(
            extra_collections
        )
        members = _load("shopify_collection_products.json")["products"]
        variant = {"title": "Default Title", "price": "100.00", "available": True}
        self.feed = [{**p, "body_html": "", "vendor": "", "variants": [variant]} for p in members]
        # A product in no collection at all.
        self.feed.append({**self.feed[0], "id": 99, "title": "Loose Part", "product_type": ""})

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(request.url.path)
        path, page = request.url.path, int(request.url.params.get("page", "1"))
        if path == "/collections.json":
            return httpx.Response(200, json={"collections": self.collections if page == 1 else []})
        if path == "/collections/object-detection/products.json":
            members = _load("shopify_collection_products.json")["products"]
            return httpx.Response(200, json={"products": members if page == 1 else []})
        if path.startswith("/collections/"):
            return httpx.Response(200, json={"products": []})
        if path == "/products.json":
            return httpx.Response(200, json={"products": self.feed if page == 1 else []})
        return httpx.Response(404)


@pytest.fixture
def shop(monkeypatch):
    shop = _Shop()
    monkeypatch.setattr(
        shopify_mod,
        "make_client",
        lambda: _RealClient(transport=httpx.MockTransport(shop.handler)),
    )

    class _Robots(robots_mod.RobotsCache):
        async def _entry(self, url):
            return robots_mod._Entry(rules=robots_mod.Rules(ROBOTS_TXT), fetched_at=0)

    monkeypatch.setattr(robots_mod, "ROBOTS", _Robots())
    monkeypatch.setattr(http_mod, "_NOT_BEFORE", {})
    pauses: list[float] = []

    async def fake_sleep(seconds):
        pauses.append(seconds)

    monkeypatch.setattr(shopify_mod.asyncio, "sleep", fake_sleep)
    shop.pauses = pauses
    return shop


async def test_collections_are_off_by_default(shop):
    page = await _adapter().fetch_page("", 1)
    assert shop.sent == ["/products.json"]
    assert all("collections" not in item.raw for item in page.items)


async def test_each_product_records_the_collections_it_is_in(shop):
    adapter = _adapter(collections=True, polite_delay=15.0)
    page = await adapter.fetch_page("", 1)
    by_title = {item.title: item for item in page.items}

    assert by_title["Ultrasonic Sensor Module"].raw["collections"] == ["Object Detection"]
    assert "collections" not in by_title["Loose Part"].raw
    assert adapter.source_categories(by_title["Ultrasonic Sensor Module"]) == [
        "Sensor",
        "Object Detection",
    ]


async def test_merchandising_and_empty_collections_cost_nothing(shop):
    adapter = _adapter(collections=True, skip_collections=["new-products"])
    await adapter.fetch_page("", 1)
    assert shop.sent == [
        "/collections.json",
        "/collections/ics/products.json",
        "/collections/object-detection/products.json",
        "/products.json",
    ], "frontpage (Shopify's), new-products (configured) and the empty Zigbee are skipped"


async def test_collection_requests_are_counted_beside_the_page(shop):
    """A run's `stats.requests` is every request the host got, not one per page."""
    adapter = _adapter(collections=True, skip_collections=["new-products"])
    assert adapter.extra_requests() == {}
    await adapter.fetch_page("", 1)
    await adapter.fetch_page("", 2)
    # Three collection requests on the first page; the second reads the map it built.
    assert adapter.extra_requests() == {"collections": 3}
    assert _adapter().extra_requests() == {}


async def test_collection_requests_are_paced_like_pages(shop):
    await _adapter(collections=True, polite_delay=15.0).fetch_page("", 1)
    # One pause before each request after the first.
    assert shop.pauses == [15.0] * (len(shop.sent) - 1)


async def test_memberships_are_read_once_per_run(shop):
    adapter = _adapter(collections=True)
    await adapter.fetch_page("", 1)
    before = len(shop.sent)
    await adapter.fetch_page("", 2)
    assert shop.sent[before:] == ["/products.json"]


async def test_a_collection_robots_disallows_is_never_requested(shop):
    """Collection handles come from the shop, not from us — a path discovered
    at runtime. robots.txt is checked against each one before it is sent."""
    shop.collections.append(
        {"handle": "sensors+motors", "title": "Sensors + Motors", "products_count": 3}
    )
    page = await _adapter(collections=True).fetch_page("", 1)
    assert not any("sensors" in path for path in shop.sent)
    assert page.items, "the disallowed collection is skipped; the sweep goes on"


def test_collections_refuse_a_feed_spread_over_runs():
    """Memberships last one run. Read again for every page of a one-page-a-day
    sweep, they would cost a sweep's worth of requests each day."""
    with pytest.raises(ValueError, match="max_pages_per_run"):
        _adapter(collections=True, max_pages_per_run=1)
    assert _adapter(max_pages_per_run=1).max_pages_per_run == 1


# Crosswalk over product_type and collections ------------------------------- #

CROSSWALK = {
    "sensor": ("electronics", "sensors"),
    "ics": ("electronics", "ics"),
    "object detection": ("electronics", "sensors"),
    "servo motors": ("electronics", "servos"),
}


def _item(product_type: str, collections: list[str]):
    adapter = _adapter(categories=CROSSWALK, prefer=["Object Detection"], collections=True)
    raw = adapter._to_raw({**_product("R20C"), "product_type": product_type})
    raw.raw["collections"] = collections
    return adapter, raw


def test_a_product_with_no_type_is_mapped_through_its_collection():
    adapter, raw = _item("", ["Frontpage", "ICs"])
    assert adapter.category_for(raw) == ("electronics", "ics")


def test_product_type_comes_before_collections():
    adapter = _adapter(categories=CROSSWALK)
    raw = adapter._to_raw({**_product("R20C"), "product_type": "Servo Motors"})
    raw.raw["collections"] = ["ICs"]
    assert adapter.category_for(raw) == ("electronics", "servos")


def test_prefer_outranks_product_type():
    adapter, raw = _item("Servo Motors", ["Object Detection"])
    assert adapter.category_for(raw) == ("electronics", "sensors")


def test_prefer_without_collections_is_refused():
    """One product_type per product leaves nothing to rank."""
    with pytest.raises(TypeError, match="prefer"):
        _adapter(categories=CROSSWALK, prefer=["Object Detection"])


def test_collections_never_make_the_source_authoritative():
    assert _adapter(collections=True, categories=CROSSWALK).authoritative_categories is False


# --------------------------------------------------------------------------- #
# Odoo: the card's change token
# --------------------------------------------------------------------------- #


def _odoo_card(html: str):
    adapter = OdooAdapter("ohmic-supply", "https://www.ohmic-supply.test", VOLTA)
    page = HTMLParser(f"<table><tr>{html}</tr></table>")
    return adapter._to_raw(page.css_first(".oe_product"))


def test_odoo_keeps_the_image_change_token():
    raw = _odoo_card((FIXTURES / "odoo_card.html").read_text())
    assert raw.raw["change_token"] == "5a0c3e1"
    assert raw.external_id == "1001"


def test_a_card_without_a_product_image_has_no_token():
    html = (FIXTURES / "odoo_card.html").read_text()
    html = html.replace("/web/image/product.template/1001/image_512/", "/web/static/placeholder/")
    assert "change_token" not in _odoo_card(html).raw
