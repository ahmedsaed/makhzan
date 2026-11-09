"""The details stage: product pages read slowly, and again only when something changed.

The owner's terms: no more requests than a fixed small budget a run, and no
re-reading a page unless the product changed (or, as a safety net, its details
have grown old). These pin the queue, the budget, the change detection, the
failure backoff, the pacing, and — the point that would silently undo all of
it — that the next list-page sweep keeps what a product page gave.

The shop here is fictional. The Odoo and Wix product pages are anonymised
fixtures shaped like the real ones.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from makhzan_schemas.contracts import ListingRead
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ListingStatus, SourceType
from makhzan_schemas.models import Listing, Source
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from worker import http as http_mod
from worker import robots as robots_mod
from worker.details import apply_details, due_listings, queue_counts
from worker.pipeline import run_source
from worker.sources import odoo, wix
from worker.sources.base import (
    TOKEN_CARD_HASH,
    TOKEN_MODIFIED,
    DetailsSettings,
    Page,
    RawItem,
    SourceAdapter,
    SupplierInfo,
)
from worker.sources.registry import build_adapter

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://detail.test"


class _AllowAll:
    async def allowed(self, url, user_agent):
        return True

    async def crawl_delay(self, url, user_agent):
        return None


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(robots_mod, "ROBOTS", _AllowAll())
    monkeypatch.setattr(http_mod, "_NOT_BEFORE", {})
    monkeypatch.setattr(http_mod.asyncio, "sleep", clock.sleep)
    monkeypatch.setattr(http_mod, "_now", clock)
    return clock


class _Shop(SourceAdapter):
    """One partition of one page listing `cards` (id -> change token), and a
    product page per id at /p/<id>."""

    source_id = "detail-shop"
    source_type = SourceType.SCRAPED
    supplier = SupplierInfo(slug="detail-shop", name="Detail Shop")
    polite_delay = 15.0
    base_url = BASE
    token_kind = TOKEN_MODIFIED

    def __init__(self, cards: dict[str, str], *, http_pages: bool = False, **settings) -> None:
        self.cards = dict(cards)
        self.details = DetailsSettings(**{"enabled": True, **settings})
        self.http_pages = http_pages
        self.sent: list[str] = []
        #: Path -> (status, headers) for answers other than 200.
        self.answers: dict[str, tuple[int, dict]] = {}

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.sent.append(request.url.path)
            status, headers = self.answers.get(request.url.path, (200, {}))
            return httpx.Response(status, headers=headers, json={})

        return httpx.MockTransport(handler)

    def details_sent(self) -> list[str]:
        return [p for p in self.sent if p.startswith("/p/")]

    async def fetch_page(self, partition: str, page: int) -> Page:
        if self.http_pages:
            async with httpx.AsyncClient(transport=self.transport()) as client:
                await http_mod.get_json(client, f"{BASE}/list/{page}")
        items = [
            RawItem(
                source=self.source_id,
                external_id=pid,
                source_url=f"{BASE}/p/{pid}",
                title=f"Widget {pid}",
                description="Card line",
                price_text="10 EGP",
                availability_text="In stock",
                images=[f"{BASE}/img/{pid}.jpg"],
                raw={"specs": {"Colour": "Red"}},
            )
            for pid in self.cards
        ]
        return Page(items, has_more=False)

    def change_token(self, raw: RawItem) -> str | None:
        return self.cards.get(raw.external_id)

    async def fetch_details(self, listing, fetcher) -> dict:
        await fetcher.get("details", f"{BASE}/p/{listing.external_id}")
        return {
            "description": f"The long description of widget {listing.external_id}.",
            "specs": {"Voltage": "5V", "Colour": "Blue"},
            "images": [f"{BASE}/img/{listing.external_id}-2.jpg"],
            "documents": [{"label": "Datasheet", "url": f"{BASE}/ds/{listing.external_id}.pdf"}],
            "brand": "Acme",
            "stock_quantity": 5,
        }


@pytest.fixture
def shop_client(monkeypatch):
    """Route the details fetcher's client to whichever shop the test sets."""
    holder: dict = {}

    def make_client(**kwargs):
        return httpx.AsyncClient(transport=holder["shop"].transport(), **kwargs)

    monkeypatch.setattr(http_mod, "make_client", make_client)
    return holder


async def _listings() -> dict[str, Listing]:
    async with SessionLocal() as session:
        rows = (
            (
                await session.execute(
                    select(Listing).options(
                        selectinload(Listing.supplier), selectinload(Listing.category)
                    )
                )
            )
            .scalars()
            .all()
        )
    return {row.external_id: row for row in rows}


async def _set_attributes(external_id: str, **changes) -> None:
    async with SessionLocal() as session:
        listing = (
            await session.execute(select(Listing).where(Listing.external_id == external_id))
        ).scalar_one()
        listing.attributes = {**listing.attributes, **changes}
        await session.commit()


# --------------------------------------------------------------------------- #
# Reading, keeping, and not re-reading
# --------------------------------------------------------------------------- #


async def test_details_are_read_merged_and_kept_by_the_next_sweep(clock, shop_client):
    shop = shop_client["shop"] = _Shop({"1": "t1", "2": "t2"})
    run = await run_source(shop.source_id, shop)

    assert sorted(shop.details_sent()) == ["/p/1", "/p/2"]
    assert run.stats["details"] == {"due": {"never_fetched": 2}, "fetched": 2}
    assert run.stats["requests"]["details"] == 2

    def check(listing: Listing) -> None:
        assert listing.description_en == "The long description of widget 1."
        # The card's own spec keeps its value; the page adds what the card lacks.
        assert listing.attributes["specs"] == {"Colour": "Red", "Voltage": "5V"}
        assert listing.images == [f"{BASE}/img/1.jpg", f"{BASE}/img/1-2.jpg"]
        assert listing.brand == "Acme"
        assert listing.attributes["details_token"] == "t1"
        assert listing.attributes["change_token"] == "t1"
        assert "stock_quantity" not in listing.attributes
        assert "stock_quantity" not in listing.attributes["details"]

    check((await _listings())["1"])

    # The next sweep rebuilds every field from the card, and must keep them.
    shop.sent.clear()
    run = await run_source(shop.source_id, shop)
    assert shop.details_sent() == [], "nothing changed, so no page is read again"
    assert "details" not in run.stats.get("requests", {})
    listing = (await _listings())["1"]
    check(listing)

    # And they reach the API through its existing fields.
    shown = ListingRead.model_validate(listing)
    assert shown.description_en == "The long description of widget 1."
    assert shown.specs == {"Colour": "Red", "Voltage": "5V"}
    assert [d.url for d in shown.documents] == [f"{BASE}/ds/1.pdf"]
    assert shown.brand == "Acme" and len(shown.images) == 2
    assert shown.stock_quantity is None


async def test_a_moved_token_is_read_again_and_only_that_one(clock, shop_client):
    shop = shop_client["shop"] = _Shop({"1": "t1", "2": "t2"})
    await run_source(shop.source_id, shop)
    shop.sent.clear()

    shop.cards["2"] = "t2-edited"
    run = await run_source(shop.source_id, shop)
    assert shop.details_sent() == ["/p/2"]
    assert run.stats["details"] == {"due": {"changed": 1}, "fetched": 1}
    assert (await _listings())["2"].attributes["details_token"] == "t2-edited"


async def test_a_limit_run_never_reads_a_product_page(clock, shop_client):
    shop = shop_client["shop"] = _Shop({"1": "t1"})
    run = await run_source(shop.source_id, shop, limit=10)
    assert shop.details_sent() == []
    assert "details" not in run.stats
    assert "details_fetched_at" not in (await _listings())["1"].attributes


async def test_a_source_with_details_off_reads_nothing(clock, shop_client):
    shop = shop_client["shop"] = _Shop({"1": "t1"}, enabled=False)
    run = await run_source(shop.source_id, shop)
    assert shop.details_sent() == [] and "details" not in run.stats


async def test_requests_and_pacing_count_the_detail_pages_within_the_budget(clock, shop_client):
    shop = shop_client["shop"] = _Shop({"1": "a", "2": "b", "3": "c"}, per_run=2, http_pages=True)
    run = await run_source(shop.source_id, shop)

    assert len(shop.details_sent()) == 2, "per_run caps the stage"
    assert run.stats["requests"] == {"pages": 1, "details": 2}
    pacing = run.stats["pacing"]
    assert pacing["requests"] == len(shop.sent) == 3
    # The first product page waits its turn after the list page, like any other.
    assert pacing["gaps"] == {"15": 2}


# --------------------------------------------------------------------------- #
# Failures
# --------------------------------------------------------------------------- #


async def test_a_broken_page_backs_off_instead_of_being_retried_every_run(clock, shop_client):
    shop = shop_client["shop"] = _Shop({"1": "t1", "2": "t2"})
    shop.answers["/p/2"] = (404, {})
    run = await run_source(shop.source_id, shop)
    assert run.stats["details"] == {"due": {"never_fetched": 2}, "fetched": 1, "failed": 1}

    broken = (await _listings())["2"].attributes
    assert broken["details_failures"] == 1
    retry = datetime.fromisoformat(broken["details_retry_at"])
    assert timedelta(hours=23) < retry - datetime.now(UTC) <= timedelta(days=1)

    shop.sent.clear()
    await run_source(shop.source_id, shop)
    assert shop.details_sent() == [], "backing off: not retried the next day"

    # Once the wait is over it is tried again, and a second failure waits longer.
    await _set_attributes(
        "2", details_retry_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    )
    await run_source(shop.source_id, shop)
    assert shop.details_sent() == ["/p/2"]
    again = (await _listings())["2"].attributes
    assert again["details_failures"] == 2
    retry = datetime.fromisoformat(again["details_retry_at"])
    assert retry - datetime.now(UTC) > timedelta(days=1, hours=23)

    # A success clears the failure record.
    del shop.answers["/p/2"]
    await _set_attributes(
        "2", details_retry_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    )
    await run_source(shop.source_id, shop)
    healed = (await _listings())["2"].attributes
    assert "details_failures" not in healed and "details_retry_at" not in healed
    assert healed["details_token"] == "t2"


async def test_a_host_backing_off_stops_the_stage_and_blames_no_listing(clock, shop_client):
    shop = shop_client["shop"] = _Shop({"1": "t1", "2": "t2"})
    http_mod._NOT_BEFORE[BASE] = time.monotonic() + 10_000
    run = await run_source(shop.source_id, shop)

    assert shop.sent == []
    assert "HostBackingOff" in run.stats["details"]["stopped"]
    assert any(e.startswith("details stopped") for e in run.stats["errors"])
    for listing in (await _listings()).values():
        assert listing.title_en, "the sweep itself is untouched"
        assert not set(listing.attributes) & {"details_failed_at", "details_fetched_at"}


async def test_a_429_that_outlasts_its_retries_stops_the_stage(clock, shop_client):
    shop = shop_client["shop"] = _Shop({"1": "t1", "2": "t2"})
    for pid in ("1", "2"):
        shop.answers[f"/p/{pid}"] = (429, {"Retry-After": "3600"})
    run = await run_source(shop.source_id, shop)

    assert len(shop.details_sent()) == 1, "one 429 asking for an hour ends the stage"
    assert "429" in run.stats["details"]["stopped"]
    for listing in (await _listings()).values():
        assert "details_failed_at" not in listing.attributes


async def test_a_403_stops_the_stage_and_blames_no_listing(clock, shop_client):
    """A shop that blocks the crawler blocks every page: one 403 ends the stage,
    and no listing is backed off for what was the host's answer."""
    shop = shop_client["shop"] = _Shop({"1": "t1", "2": "t2"})
    for pid in ("1", "2"):
        shop.answers[f"/p/{pid}"] = (403, {})
    run = await run_source(shop.source_id, shop)

    assert len(shop.details_sent()) == 1
    assert "403" in run.stats["details"]["stopped"]
    for listing in (await _listings()).values():
        assert "details_failed_at" not in listing.attributes


async def test_a_run_whose_sweep_failed_reads_no_product_page(clock, shop_client):
    """A host refusing list pages is not then asked for product pages."""
    seeded = _Shop({"1": "t1"}, enabled=False)
    await run_source(seeded.source_id, seeded)
    shop = shop_client["shop"] = _Shop({"1": "t1"}, http_pages=True)
    shop.answers["/list/1"] = (403, {})
    run = await run_source(shop.source_id, shop)

    assert shop.details_sent() == []
    assert "details" not in run.stats.get("requests", {})


async def test_a_detail_page_is_retried_once_not_five_times(clock, shop_client):
    """Retries are requests too: a failing product page costs at most two."""
    shop = shop_client["shop"] = _Shop({"1": "t1"})
    shop.answers["/p/1"] = (503, {})
    await run_source(shop.source_id, shop)
    assert shop.details_sent().count("/p/1") == 2


# --------------------------------------------------------------------------- #
# The queue
# --------------------------------------------------------------------------- #


async def _seed_queue() -> None:
    """Six listings in every state the queue tells apart."""
    shop = _Shop({k: "t" for k in "ABCDEF"}, enabled=False)
    await run_source(shop.source_id, shop)
    now = datetime.now(UTC)
    ago = lambda days: (now - timedelta(days=days)).isoformat()  # noqa: E731
    # A: read before, and its token has moved since.
    await _set_attributes("A", details_fetched_at=ago(3), details_token="old")
    # B, C: never read; C seen more recently than B.
    async with SessionLocal() as session:
        await session.execute(
            update(Listing)
            .where(Listing.external_id == "B")
            .values(first_seen_at=now - timedelta(days=10))
        )
        await session.execute(
            update(Listing)
            .where(Listing.external_id == "C")
            .values(first_seen_at=now - timedelta(days=1))
        )
        await session.commit()
    # D, E: read long ago, unchanged since; E longer ago than D.
    await _set_attributes("D", details_fetched_at=ago(100), details_token="t")
    await _set_attributes("E", details_fetched_at=ago(200), details_token="t")
    # F: read recently, unchanged: not due.
    await _set_attributes("F", details_fetched_at=ago(5), details_token="t")


async def test_the_queue_spends_the_budget_changed_then_new_then_stale(clock):
    await _seed_queue()
    settings = DetailsSettings(enabled=True, per_run=10, max_age_days=90)
    async with SessionLocal() as session:
        due = await due_listings(session, "detail-shop", settings)
    assert [(listing.external_id, reason) for listing, reason in due] == [
        ("A", "changed"),
        ("C", "never_fetched"),  # newest first
        ("B", "never_fetched"),
        ("E", "stale"),  # oldest first
        ("D", "stale"),
    ]

    async with SessionLocal() as session:
        due = await due_listings(session, "detail-shop", DetailsSettings(per_run=2))
        assert [listing.external_id for listing, _ in due] == ["A", "C"]
        counts = await queue_counts(session, "detail-shop", settings)
    assert counts == {
        "changed": 1,
        "never_fetched": 2,
        "stale": 2,
        "fetched": 4,
        "backing_off": 0,
    }


async def test_age_alone_makes_a_listing_due_and_a_longer_max_age_does_not(clock):
    await _seed_queue()
    async with SessionLocal() as session:
        lenient = await due_listings(
            session, "detail-shop", DetailsSettings(per_run=10, max_age_days=365)
        )
    assert "stale" not in {reason for _, reason in lenient}


async def test_backing_off_and_archived_listings_are_not_due(clock):
    await _seed_queue()
    later = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    await _set_attributes("A", details_retry_at=later)
    async with SessionLocal() as session:
        await session.execute(
            update(Listing).where(Listing.external_id == "C").values(status=ListingStatus.ARCHIVED)
        )
        await session.commit()
        due = await due_listings(session, "detail-shop", DetailsSettings(per_run=10))
        counts = await queue_counts(session, "detail-shop", DetailsSettings(per_run=10))
    assert [listing.external_id for listing, _ in due] == ["B", "E", "D"]
    assert counts["backing_off"] == 1


# --------------------------------------------------------------------------- #
# Merging
# --------------------------------------------------------------------------- #


def test_applying_details_twice_changes_nothing():
    fields = {
        "description_en": "Card",
        "description_ar": None,
        "brand": "CardBrand",
        "images": ["a.jpg"],
        "attributes": {
            "specs": {"A": "1"},
            "documents": [{"label": "x", "url": "https://s.test/x.pdf"}],
            "details": {
                "description": "Page",
                "brand": "PageBrand",
                "images": ["a.jpg", "b.jpg"],
                "specs": {"A": "2", "B": "3"},
                "documents": [{"label": "y", "url": "https://s.test/x.pdf"}],
                "supplier_sku": "SKU-1",
            },
        },
    }
    once = apply_details(fields)
    assert apply_details(once) == once
    assert once["description_en"] == "Page"
    assert once["brand"] == "CardBrand", "a page's brand fills a gap, never overwrites"
    assert once["images"] == ["a.jpg", "b.jpg"]
    assert once["attributes"]["specs"] == {"A": "1", "B": "3"}
    assert len(once["attributes"]["documents"]) == 1
    assert once["attributes"]["supplier_sku"] == "SKU-1"


def test_an_arabic_description_goes_to_the_arabic_field():
    out = apply_details(
        {
            "description_en": "Card",
            "description_ar": None,
            "brand": None,
            "images": [],
            "attributes": {"details": {"description": "وصف المنتج الكامل"}},
        }
    )
    assert out["description_ar"] == "وصف المنتج الكامل" and out["description_en"] == "Card"


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #


def _row(adapter: str, **config) -> Source:
    return Source(
        source_id="s",
        adapter=adapter,
        base_url="https://shop.test",
        enabled=True,
        supplier={"slug": "s", "name": "S"},
        config=config,
    )


def test_details_are_configured_only_where_an_adapter_can_fetch_them():
    built = build_adapter(_row("odoo", details={"enabled": True, "per_run": 60}))
    assert built.details == DetailsSettings(enabled=True, per_run=60, max_age_days=90)
    assert build_adapter(_row("odoo")).details == DetailsSettings()
    wix_row = _row("wix", galleries=["/shop"], details={"enabled": False})
    assert build_adapter(wix_row).details.enabled is False

    for adapter in ("woocommerce", "shopify"):
        with pytest.raises(TypeError, match="details"):
            build_adapter(_row(adapter, details={"enabled": False}))


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ({"enabled": False, "per_rn": 5}, TypeError),
        ({"enabled": "yes"}, TypeError),
        ({"per_run": 0}, ValueError),
        ({"max_age_days": True}, ValueError),
        ("on", TypeError),
    ],
)
def test_a_bad_details_setting_is_an_error(value, error):
    with pytest.raises(error):
        DetailsSettings.from_config(value)


# --------------------------------------------------------------------------- #
# Odoo
# --------------------------------------------------------------------------- #


def test_odoo_product_page():
    page = (FIXTURES / "odoo_product.html").read_text()
    out = odoo.parse_product_page(page, "https://shop.example.test")

    assert out["description"].startswith("INTRODUCTION\nA waterproof ultrasonic")
    assert out["specs"]["Operating Voltage"] == "3.3~5V"
    assert out["specs"]["Average Current"] == "8mA"
    assert out["brand"] == "Acme Sensors"
    # The page's itemprop=mpn is the shop's internal reference, never read as one.
    assert "mfr_part_number" not in out
    assert "KIT.US.WATERPROOF.ULTRASONIC" not in str(out)
    # A PDF anywhere, and every link under the DOCUMENTS heading; not the
    # delivery-policy link under the next heading.
    assert [d["url"] for d in out["documents"]] == [
        "https://shop.example.test/web/content/77/ultrasonic-datasheet.pdf",
        "https://wiki.example.test/Ultrasonic_Sensor_A0221AU",
        "https://cloud.example.test/publink/show?code=XZabc",
    ]
    assert out["videos"] == [
        {"label": "Video", "url": "https://www.youtube.com/watch?v=AbCdEfGhIjK"}
    ]
    # The extra photos only: the template image is the card's.
    assert out["images"] == [
        "https://shop.example.test/web/image/product.image/2426/image_1024/Ultrasonic?unique=1a2b3c4",
        "https://shop.example.test/web/image/product.image/2427/image_1024/Ultrasonic?unique=1a2b3c4",
    ]
    assert not any("stock" in key for key in out)


def test_odoo_refuses_a_page_that_is_not_a_product():
    with pytest.raises(ValueError):
        odoo.parse_product_page(
            "<html><body><div id='wrap'>Shop</div></body></html>", "https://s.test"
        )


def test_odoo_reads_only_its_own_product_pages_without_their_query():
    base = "https://shop.example.test"
    assert (
        odoo._product_url(f"{base}/shop/sensor-1002?category=27", base)
        == f"{base}/shop/sensor-1002"
    )
    for bad in (None, "https://elsewhere.test/shop/x-1", f"{base}/contactus"):
        with pytest.raises(ValueError):
            odoo._product_url(bad, base)


def test_odoo_change_token_is_the_card_images_unique():
    adapter = odoo.OdooAdapter(
        "odoo-test", "https://shop.example.test", SupplierInfo(slug="o", name="O")
    )
    assert adapter.token_kind == TOKEN_MODIFIED
    raw = RawItem(source="odoo-test", raw={"change_token": "9d9f242"})
    assert adapter.change_token(raw) == "9d9f242"


# --------------------------------------------------------------------------- #
# Wix
# --------------------------------------------------------------------------- #


def test_wix_product_page():
    page = (FIXTURES / "wix" / "product_page.html").read_text()
    out = wix.parse_product_page(page, "https://www.shop.example.test")

    assert out["description"].startswith("Black PLA+ filament by Acme, made in Egypt.")
    assert "Print Settings" in out["description"] and "Keep sealed and dry." in out["description"]
    # A line of several settings is read as several specs.
    assert out["specs"] == {
        "Diameter": "1.75 mm",
        "Tolerance": "±0.05 mm",
        "Net Weight": "1 kg",
        "Print Temp": "210-230oC",
        "Print Speed": "100-300mm/s",
        "Bed Temp": "60-65oC",
    }
    assert out["documents"] == [
        {
            "label": "technical data sheet",
            "url": "https://www.shop.example.test/_files/ugd/a1b2c3_0123456789abcdef.pdf",
        }
    ]
    assert out["videos"][0]["url"] == "https://www.youtube.com/watch?v=AbCdEfGhIjK"
    assert "brand" not in out
    assert "38" not in str(out), "the per-variant stock count is never kept"


def _wix_product(**changes) -> dict:
    product = {
        "id": "p1",
        "urlPart": "black-pla",
        "name": "Black PLA +",
        "price": 695,
        "comparePrice": 0,
        "sku": "S1",
        "ribbon": "Best Seller",
        "isInStock": True,
        "inventory": {"status": "in_stock", "quantity": 0},
        "media": [{"url": "a1b2c3_1~mv2.jpg", "altText": "Acme Black PLA+ 3D printer filament"}],
    }
    return {**product, **changes}


def test_wix_change_token_is_a_card_hash_that_ignores_stock():
    adapter = wix.WixStoresAdapter(
        "wix-test", "https://www.shop.example.test", SupplierInfo(slug="w", name="W"),
        galleries=["/shop"],
    )  # fmt: skip
    assert adapter.token_kind == TOKEN_CARD_HASH

    def token(**changes) -> str:
        return adapter.change_token(adapter._to_raw(_wix_product(**changes), None))

    base = token()
    assert base and base == token()
    assert token(isInStock=False, inventory={"status": "out_of_stock"}) == base
    for change in (
        {"price": 650},
        {"comparePrice": 600},
        {"name": "Black PLA+"},
        {"ribbon": "New Arrival"},
        {"media": [{"url": "a1b2c3_2~mv2.jpg"}]},
    ):
        assert token(**change) != base, change


async def test_wix_reads_only_its_own_product_pages():
    adapter = wix.WixStoresAdapter(
        "wix-test", "https://www.shop.example.test", SupplierInfo(slug="w", name="W"),
        galleries=["/shop"],
    )  # fmt: skip
    listing = Listing(source_url="https://www.shop.example.test/shop?lightbox=1")
    with pytest.raises(ValueError):
        await adapter.fetch_details(listing, fetcher=None)
