"""Phase 1 of the crawler scheduling plan (docs/crawler-scheduling.md).

  - T1: ending a partition on a short page, in shadow (today's behaviour, plus a
    verdict on whether the stop would have been right) and live;
  - T4: archive candidates are asked about by id (WooCommerce `include`) before
    they are archived, and a failed check holds the cycle open, for at most a
    cycle;
  - T12: the Odoo shop's sitemap vetoes an archive, and only a product page read
    counts as seen;
  - T10: the details backfill reads important listings first, and a card-hash
    source's revisit interval adapts.

Nothing reaches the network: an `httpx.MockTransport` plays each shop, and
robots.txt is stubbed to allow with no Crawl-delay.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ListingStatus, SourceType, StockSignal
from makhzan_schemas.models import IngestionRun, Listing, Product, Source, SourceCursor, Supplier
from sqlalchemy import select, update
from worker import http as http_mod
from worker.details import (
    DETAIL_KEYS,
    MAX_INTERVAL_DAYS,
    MIN_INTERVAL_DAYS,
    carry_details,
    due_listings,
    next_interval,
)
from worker.pipeline import run_source
from worker.robots import ROBOTS
from worker.sources import odoo as odoo_mod
from worker.sources import woocommerce as woo_mod
from worker.sources.base import DetailsSettings, SupplierInfo
from worker.sources.odoo import OdooAdapter
from worker.sources.registry import build_adapter
from worker.sources.shopify import ShopifyAdapter
from worker.sources.short_page import ShortPageEnd
from worker.sources.woocommerce import WooCommerceAdapter

WOO = "https://woo.test"
ODOO = "https://odoo.test"


@pytest.fixture
def allow_robots(monkeypatch):
    async def allowed(url, user_agent):
        return True

    async def no_delay(url, user_agent):
        return None

    monkeypatch.setattr(ROBOTS, "allowed", allowed)
    monkeypatch.setattr(ROBOTS, "crawl_delay", no_delay)


def _params(request: httpx.Request) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlsplit(str(request.url)).query).items()}


# --------------------------------------------------------------------------- #
# T1: the tracker itself
# --------------------------------------------------------------------------- #


def test_shadow_changes_nothing_and_agrees_when_the_next_page_is_the_end():
    tracker = ShortPageEnd("shadow")
    assert tracker.page("p", 1, ["1", "2"], short=False, end=False) is False
    assert tracker.page("p", 2, ["3"], short=True, end=False) is False, "shadow never stops"
    assert tracker.page("p", 3, [], short=True, end=True) is False
    report = tracker.report()
    assert report["compared"] == 1 and report["agreed"] == 1
    assert report["disagreements"] == 0 and report["saved"] == 1
    assert "pending" not in report


def test_shadow_counts_a_short_page_that_was_not_the_last():
    tracker = ShortPageEnd("shadow")
    tracker.page("cat", 1, ["1"], short=True, end=False)
    tracker.page("cat", 2, ["2", "3"], short=False, end=False)
    report = tracker.report()
    assert report["disagreements"] == 1
    assert report["disagreed"] == ["cat p1"]


def test_a_verdict_left_for_the_next_run_is_carried_in_the_report():
    first = ShortPageEnd("shadow")
    first.page("instock", 4, ["7", "8"], short=True, end=False)
    report = first.report()
    assert report["pending"] == {"instock": {"page": 4, "ids": ["7", "8"]}}

    second = ShortPageEnd("shadow")
    second.restore(report)
    # Odoo's repeat of the last page: the same ids, nothing new.
    second.page("instock", 5, ["7", "8"], short=True, end=False)
    again = second.report()
    assert again["compared"] == 1 and again["disagreements"] == 0
    assert "pending" not in again, "resolved, and the repeat itself is not a new would-stop"


def test_live_stops_on_a_short_page_and_off_does_nothing():
    live = ShortPageEnd("live")
    assert live.page("p", 1, ["1"], short=True, end=False) is True
    assert live.report() == {"mode": "live", "saved": 1}
    off = ShortPageEnd("off")
    assert off.page("p", 1, ["1"], short=True, end=False) is False
    assert off.report() == {}


def test_an_unknown_mode_is_refused_and_only_paged_adapters_take_the_key():
    supplier = SupplierInfo(slug="s", name="S")
    with pytest.raises(ValueError, match="end_on_short_page"):
        WooCommerceAdapter("s", WOO, supplier, end_on_short_page="yes")
    assert ShopifyAdapter("s", WOO, supplier).short_page.mode == "shadow"
    assert OdooAdapter("s", ODOO, supplier, end_on_short_page="live").short_page.mode == "live"
    wix = Source(
        source_id="w",
        adapter="wix",
        base_url="https://wix.test",
        supplier={"slug": "w", "name": "W"},
        config={"galleries": ["/shop"], "end_on_short_page": "live"},
    )
    with pytest.raises(TypeError):
        build_adapter(wix)


# --------------------------------------------------------------------------- #
# T1: Odoo, whose end is a repeat of its last page
# --------------------------------------------------------------------------- #


def _odoo_page(ids: list[int], page: int, last: int | None) -> str:
    cards = "".join(
        f'<div class="oe_product"><a href="/shop/widget-{i}">'
        f'<span itemprop="name">Widget {i}</span></a><span itemprop="price">10.0</span></div>'
        for i in ids
    )
    pager = ""
    if last is not None and last > 1:
        numbers = "".join(
            f'<li class="page-item{" active" if n == page else ""}"><a class="page-link">{n}</a></li>'
            for n in range(1, last + 1)
        )
        nxt = "page-item disabled" if page >= last else "page-item"
        pager = (
            f'<ul class="pagination"><li class="page-item"><a>Prev</a></li>{numbers}'
            f'<li class="{nxt}"><a class="page-link">Next</a></li></ul>'
        )
    return f"<html><body>{cards}{pager}</body></html>"


def _odoo_shop(pages: dict[int, list[int]], *, pager: bool = True):
    last = max(pages)

    async def fake_get_text(client, url, params):
        page = min(params["page"], last)  # Odoo clamps to its last page
        return _odoo_page(pages[page], page, last if pager else None)

    return fake_get_text


async def test_odoo_shadow_keeps_reading_to_the_repeat_and_records_agreement(monkeypatch):
    monkeypatch.setattr(odoo_mod, "get_text", _odoo_shop({1: [1, 2], 2: [3]}))
    adapter = OdooAdapter("t", ODOO, SupplierInfo(slug="t", name="T"))

    assert (await adapter.fetch_page("", 1)).has_more is True
    assert (await adapter.fetch_page("", 2)).has_more is True, "shadow: today's behaviour"
    assert (await adapter.fetch_page("", 3)).has_more is False, "the repeat ends it"
    report = adapter.run_report()["short_page"]
    assert report == {
        "mode": "shadow",
        "compared": 1,
        "agreed": 1,
        "disagreements": 0,
        "saved": 1,
        "full_last_page": 0,
    }


async def test_odoo_live_ends_on_the_page_its_pager_calls_last(monkeypatch):
    monkeypatch.setattr(odoo_mod, "get_text", _odoo_shop({1: [1, 2], 2: [3]}))
    adapter = OdooAdapter("t", ODOO, SupplierInfo(slug="t", name="T"), end_on_short_page="live")

    assert (await adapter.fetch_page("", 1)).has_more is True
    second = await adapter.fetch_page("", 2)
    assert second.has_more is False and [i.external_id for i in second.items] == ["3"]
    assert adapter.run_report()["short_page"] == {"mode": "live", "saved": 1}


async def test_odoo_shadow_catches_a_page_without_a_pager_that_was_not_the_last(monkeypatch):
    """Page 1 without a pager reads as "only page"; page 2 proves it wrong."""
    monkeypatch.setattr(odoo_mod, "get_text", _odoo_shop({1: [1, 2], 2: [3]}, pager=False))
    adapter = OdooAdapter("t", ODOO, SupplierInfo(slug="t", name="T"))
    await adapter.fetch_page("", 1)
    await adapter.fetch_page("", 2)
    report = adapter.run_report()["short_page"]
    assert report["disagreements"] == 1 and report["disagreed"] == ["default p1"]


# --------------------------------------------------------------------------- #
# A fake WooCommerce shop, for T1 across runs and T4
# --------------------------------------------------------------------------- #


def _product(pid: int, status: str = "instock") -> dict:
    return {
        "id": pid,
        "name": f"Widget {pid}",
        "permalink": f"{WOO}/p/{pid}",
        "prices": {"price": str(1000 + pid), "currency_minor_unit": 2, "currency_code": "EGP"},
        "categories": [],
        "images": [],
        "is_in_stock": status != "outofstock",
        "is_on_backorder": status == "onbackorder",
    }


class FakeWoo:
    """`catalogue` is the shop as it is now: id -> stock status, paged by id."""

    def __init__(self) -> None:
        self.catalogue: dict[int, str] = {}
        self.requests: list[dict] = []
        self.include_status = 200

    def handle(self, request: httpx.Request) -> httpx.Response:
        params = _params(request)
        self.requests.append(params)
        if "include" in params:
            if self.include_status != 200:
                return httpx.Response(self.include_status, json={"code": "error"})
            wanted = {int(i) for i in params["include"].split(",")}
            rows = [_product(i, s) for i, s in sorted(self.catalogue.items()) if i in wanted]
            return httpx.Response(200, json=rows)
        size, page = int(params["per_page"]), int(params["page"])
        rows = [
            _product(i, s) for i, s in sorted(self.catalogue.items()) if s == params["stock_status"]
        ]
        return httpx.Response(200, json=rows[(page - 1) * size : page * size])

    def client(self, **kwargs) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle), **kwargs)

    def included(self) -> list[str]:
        return [p["include"] for p in self.requests if "include" in p]


@pytest.fixture
def woo(monkeypatch, allow_robots):
    shop = FakeWoo()
    monkeypatch.setattr(http_mod, "make_client", shop.client)
    monkeypatch.setattr(woo_mod, "make_client", shop.client)
    monkeypatch.setattr(woo_mod, "PER_PAGE", 2)
    return shop


def _woo_adapter(**options) -> WooCommerceAdapter:
    options = dict(
        polite_delay=0,
        variations=False,
        category_tree=False,
        contact=False,
        max_pages_per_run=1,
        **options,
    )
    return WooCommerceAdapter("woo", WOO, SupplierInfo(slug="woo", name="Woo"), **options)


async def _run_until_cycle(**options) -> list[IngestionRun]:
    runs = []
    for _ in range(10):
        runs.append(await run_source("woo", _woo_adapter(**options)))
        if runs[-1].stats.get("cycle"):
            return runs
    raise AssertionError("the cycle never closed")


async def _status_of(external_id: str) -> Listing:
    async with SessionLocal() as session:
        return (
            await session.execute(select(Listing).where(Listing.external_id == external_id))
        ).scalar_one()


async def test_a_listing_skipped_by_paging_drift_is_confirmed_and_kept(woo):
    """W5, as production showed it (48 of 173 archived listings came back under
    the same id): a removal on an already-read page shifts the next product onto
    it, the sweep never reaches it, and the cycle used to archive it.
    """
    woo.catalogue = {i: "instock" for i in range(1, 6)}
    await _run_until_cycle()

    # Cycle 2, run 1 reads in-stock page 1 (1, 2). Then the shop drops 1 (read
    # already) and 5 (really gone), so 3 moves onto page 1 and run 2's page 2
    # holds only 4: 3 is never reached this cycle.
    first = await run_source("woo", _woo_adapter())
    assert not first.stats.get("cycle")
    del woo.catalogue[1], woo.catalogue[5]
    runs = [first, *await _run_until_cycle()]

    closing = runs[-1]
    assert sorted(woo.included()[-1].split(",")) == ["3", "5"], "both candidates, one request"
    assert (await _status_of("3")).status == ListingStatus.ACTIVE, "skipped, not gone: kept"
    assert (await _status_of("5")).status == ListingStatus.ARCHIVED
    assert closing.stats["archived"] == 1
    assert closing.stats["archive_confirm"] == {
        "candidates": 2,
        "offered": 2,
        "via": "store api include",
        "kept": 1,
        "absent": 1,
    }
    assert closing.stats["requests"]["confirm"] == 1
    # The confirmed listing was re-read with its price, so it is verified too.
    kept = await _status_of("3")
    assert kept.last_verified_at > first.started_at

    # T1 in shadow, across runs: page 2 (one product) was a run's last page,
    # and the next run's empty page 3 agreed with it.
    reports = [r.stats["source_report"]["short_page"] for r in runs]
    assert sum(r["compared"] for r in reports) >= 1
    assert sum(r["disagreements"] for r in reports) == 0


async def test_a_failed_confirmation_holds_the_cycle_for_the_next_run(woo):
    woo.catalogue = {1: "instock", 2: "instock"}
    await _run_until_cycle()
    del woo.catalogue[2]
    woo.include_status = 500

    runs = []
    for _ in range(5):
        runs.append(await run_source("woo", _woo_adapter()))
        if runs[-1].stats.get("archive_confirm"):
            break
    stuck = runs[-1]
    assert "failed" in stuck.stats["archive_confirm"]
    assert not stuck.stats.get("cycle") and not stuck.stats.get("archived")
    assert (await _status_of("2")).status == ListingStatus.ACTIVE
    async with SessionLocal() as session:
        cursors = (await session.execute(select(SourceCursor))).scalars().all()
    assert cursors and all(c.exhausted for c in cursors), "the cycle stays open"

    # Next run: the shop answers, the cycle closes, and 2 is archived.
    woo.include_status = 200
    pages_before = sum(1 for p in woo.requests if "stock_status" in p)
    after = await run_source("woo", _woo_adapter())
    assert after.stats.get("cycle") and after.stats["archived"] == 1
    assert sum(1 for p in woo.requests if "stock_status" in p) == pages_before, "no page re-read"
    assert (await _status_of("2")).status == ListingStatus.ARCHIVED


async def test_a_confirmation_failing_for_a_whole_cycle_archives_as_before(woo):
    woo.catalogue = {1: "instock", 2: "instock"}
    await _run_until_cycle()
    del woo.catalogue[2]
    woo.include_status = 500
    for _ in range(5):
        run = await run_source("woo", _woo_adapter())
        if run.stats.get("archive_confirm"):
            break
    # The sweep finished long ago (longer than the cycle took, and a day).
    async with SessionLocal() as session:
        await session.execute(
            update(SourceCursor).values(updated_at=datetime.now(UTC) - timedelta(days=3))
        )
        await session.commit()

    late = await run_source("woo", _woo_adapter())
    assert late.stats["archive_confirm"]["overdue"] is True
    assert late.stats.get("cycle") and late.stats["archived"] == 1


async def test_a_limited_run_asks_nothing(woo):
    woo.catalogue = {1: "instock"}
    await run_source("woo", _woo_adapter(), limit=5)
    assert woo.included() == []


# --------------------------------------------------------------------------- #
# T12: the Odoo shop's sitemap as an archive veto
# --------------------------------------------------------------------------- #


class FakeOdoo:
    def __init__(self) -> None:
        self.shop: list[int] = []
        self.sitemap: list[int] = []
        self.pages: dict[int, int] = {}  # product id -> status of its page
        self.requests: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(path)
        if path == "/shop":
            return httpx.Response(200, text=_odoo_page(self.shop, 1, None))
        if path == "/sitemap.xml":
            locs = "".join(f"<url><loc>{ODOO}/shop/widget-{i}</loc></url>" for i in self.sitemap)
            locs += f"<url><loc>{ODOO}/shop/category/sensors-3</loc></url>"
            return httpx.Response(200, text=f"<urlset>{locs}</urlset>")
        pid = int(path.rsplit("-", 1)[-1])
        status = self.pages.get(pid, 404)
        body = '<html><section id="product_detail">Widget</section></html>' if status == 200 else ""
        return httpx.Response(status, text=body)

    def client(self, **kwargs) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle), **kwargs)


@pytest.fixture
def odoo(monkeypatch, allow_robots):
    shop = FakeOdoo()
    monkeypatch.setattr(http_mod, "make_client", shop.client)
    monkeypatch.setattr(odoo_mod, "make_client", shop.client)
    return shop


def _odoo_adapter() -> OdooAdapter:
    return OdooAdapter("odoo", ODOO, SupplierInfo(slug="odoo", name="Odoo"), polite_delay=0)


async def _odoo_listing(pid: int) -> Listing:
    async with SessionLocal() as session:
        return (
            await session.execute(select(Listing).where(Listing.external_id == str(pid)))
        ).scalar_one()


async def test_the_sitemap_holds_a_candidate_and_its_page_keeps_it(odoo):
    odoo.shop = [1, 2, 3, 4]
    first = await run_source("odoo", _odoo_adapter())
    assert first.stats.get("cycle")
    verified = (await _odoo_listing(2)).last_verified_at

    # The sweep sees only 1. 2 and 4 are still in the sitemap (2's page is
    # there, 4's is gone); 3 is in neither.
    odoo.shop, odoo.sitemap, odoo.pages = [1], [1, 2, 4], {2: 200}
    second = await run_source("odoo", _odoo_adapter())

    assert second.stats.get("cycle")
    two = await _odoo_listing(2)
    assert two.status == ListingStatus.ACTIVE
    assert two.last_seen_at > first.finished_at, "the product page read is a sighting"
    assert two.last_verified_at == verified, "no price was read"
    assert (await _odoo_listing(3)).status == ListingStatus.ARCHIVED
    assert (await _odoo_listing(4)).status == ListingStatus.ARCHIVED
    report = second.stats["archive_confirm"]
    assert report["via"] == "sitemap" and report["held_by_sitemap"] == 2
    assert report["kept"] == 1 and report["absent"] == 2
    assert second.stats["requests"]["confirm"] == 3, "the sitemap and two product pages"
    assert odoo.requests.count("/sitemap.xml") == 1


async def test_sitemap_presence_alone_is_never_a_sighting(odoo, monkeypatch):
    """Held over the page cap: not archived, not seen, and the cycle waits."""
    odoo.shop = [1, 2]
    first = await run_source("odoo", _odoo_adapter())
    odoo.shop, odoo.sitemap, odoo.pages = [1], [1, 2], {2: 200}
    monkeypatch.setattr(odoo_mod, "CONFIRM_PAGES", 0)

    held = await run_source("odoo", _odoo_adapter())
    two = await _odoo_listing(2)
    assert two.status == ListingStatus.ACTIVE
    assert two.last_seen_at < first.finished_at, "the sitemap is not a sighting"
    assert held.stats["archive_confirm"]["held"] == 1
    assert not held.stats.get("cycle")

    monkeypatch.setattr(odoo_mod, "CONFIRM_PAGES", 20)
    done = await run_source("odoo", _odoo_adapter())
    assert done.stats.get("cycle") and not done.stats.get("archived")
    assert (await _odoo_listing(2)).last_seen_at > first.finished_at


async def test_an_odoo_sitemap_that_fails_holds_the_archive(odoo):
    odoo.shop = [1, 2]
    await run_source("odoo", _odoo_adapter())
    odoo.shop = [1]
    odoo.sitemap = []  # lists no products: not evidence that none exist
    run = await run_source("odoo", _odoo_adapter())
    assert "failed" in run.stats["archive_confirm"]
    assert (await _odoo_listing(2)).status == ListingStatus.ACTIVE


# --------------------------------------------------------------------------- #
# T10: details ordering and adaptive revisits
# --------------------------------------------------------------------------- #


async def _details_shop(rows: list[dict]) -> None:
    async with SessionLocal() as session:
        supplier = Supplier(id=uuid.uuid4(), slug="d", name="D", source_type=SourceType.SCRAPED)
        session.add(supplier)
        await session.flush()
        now = datetime.now(UTC)
        for i, row in enumerate(rows):
            product = None
            if row.get("suppliers"):
                product = Product(group_key=f"g{i}", supplier_count=row["suppliers"])
                session.add(product)
                await session.flush()
            session.add(
                Listing(
                    supplier_id=supplier.id,
                    source="d",
                    source_type=SourceType.SCRAPED,
                    external_id=row["id"],
                    product_id=product.id if product else None,
                    stock_signal=row.get("stock", StockSignal.IN_STOCK),
                    first_seen_at=now - timedelta(days=row.get("age", 0)),
                    attributes=row.get("attributes", {}),
                )
            )
        await session.commit()


async def test_the_backfill_reads_important_listings_first_then_newest():
    await _details_shop(
        [
            {"id": "new-oos", "stock": StockSignal.OUT_OF_STOCK, "age": 0},
            {"id": "old-oos", "stock": StockSignal.OUT_OF_STOCK, "age": 9},
            {"id": "in-stock", "age": 5},
            {"id": "compared-oos", "stock": StockSignal.OUT_OF_STOCK, "suppliers": 2, "age": 7},
            {"id": "compared-in-stock", "suppliers": 3, "age": 8},
            {"id": "single-product", "suppliers": 1, "age": 1},
        ]
    )
    async with SessionLocal() as session:
        due = await due_listings(session, "d", DetailsSettings(enabled=True, per_run=10))
    assert [row.external_id for row, _ in due] == [
        "compared-in-stock",  # 2.5
        "compared-oos",  # 2.0
        "single-product",  # 1.5, newer
        "in-stock",  # 1.5
        "new-oos",  # 1.0, newest
        "old-oos",
    ]


def test_the_interval_grows_on_an_unchanged_page_and_shrinks_on_a_changed_one():
    read = {"details_fetched_at": "2026-01-01T00:00:00+00:00", "details": {"description": "a"}}
    assert next_interval({}, {"description": "a"}, 90) is None, "a first read sets nothing"
    assert next_interval(read, {"description": "a"}, 90) == 126.0
    assert next_interval(read, {"description": "b"}, 90) == 72.0
    assert next_interval({**read, "details_interval_days": 150}, read["details"], 90) == (
        MAX_INTERVAL_DAYS
    )
    assert next_interval({**read, "details_interval_days": 32}, {"x": 1}, 90) == MIN_INTERVAL_DAYS


async def test_a_card_hash_source_uses_each_listings_own_interval():
    fetched = (datetime.now(UTC) - timedelta(days=50)).isoformat()
    common = {"details_fetched_at": fetched, "change_token": "t", "details_token": "t"}
    await _details_shop(
        [
            {"id": "short", "attributes": {**common, "details_interval_days": 40}},
            {"id": "long", "attributes": {**common, "details_interval_days": 120}},
            {"id": "unset", "attributes": common},
        ]
    )
    settings = DetailsSettings(enabled=True, per_run=10, max_age_days=45)
    async with SessionLocal() as session:
        adaptive = await due_listings(session, "d", settings, adaptive=True)
        fixed = await due_listings(session, "d", settings)
    assert sorted(row.external_id for row, _ in adaptive) == ["short", "unset"]
    assert sorted(row.external_id for row, _ in fixed) == ["long", "short", "unset"]


def test_the_interval_survives_the_next_list_page_sweep():
    assert "details_interval_days" in DETAIL_KEYS
    stored = {"details_interval_days": 126.0, "details_fetched_at": "x", "price": 1}
    assert carry_details(stored, {"price": 2})["details_interval_days"] == 126.0


# --------------------------------------------------------------------------- #
# make status
# --------------------------------------------------------------------------- #


def _status():
    path = Path(__file__).resolve().parents[3] / "scripts" / "status.py"
    spec = importlib.util.spec_from_file_location("makhzan_status_phase1", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_status_says_whether_the_short_page_stop_is_ready(capsys):
    now = datetime.now(UTC)
    cycle_start = now - timedelta(days=8)

    def run(days_ago: float, report: dict, **stats) -> IngestionRun:
        return IngestionRun(
            source="woo",
            source_type=SourceType.SCRAPED,
            started_at=now - timedelta(days=days_ago),
            finished_at=now - timedelta(days=days_ago),
            stats={"source_report": {"short_page": report}, **stats},
        )

    shadow = {"mode": "shadow", "compared": 3, "disagreements": 0, "saved": 3}
    async with SessionLocal() as session:
        session.add_all(
            [
                run(1, shadow, cycle={"cycle_started_at": cycle_start.isoformat()}),
                run(3, shadow),
                run(20, {**shadow, "disagreements": 4}),  # before the cycle: not counted
            ]
        )
        await session.commit()
        await _status().short_page_end(session, None)
    out = capsys.readouterr().out
    assert "short-page stop: shadow, 6 partitions compared" in out
    assert "0 disagreements" in out
    assert 'ready: end_on_short_page = "live"' in out
