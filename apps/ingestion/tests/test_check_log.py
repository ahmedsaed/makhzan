"""Phase 0 of the crawler scheduling plan: measure, sending nothing more.

- The check log (`listings.checks`, `changes`, `first_checked_at`): every real
  read of a listing's price or stock counts, a change only when the price or
  stock moved, and a `limit=` run never.
- `price_observations.via` names the lane; everything today is the sweep.
- `stats.validators` counts ETag / Last-Modified per host, and stays out of
  `stats.pacing`, which /how-we-crawl publishes.
- `stats.categories` counts a sweep setting, moving or clearing a stored
  listing's category (decision D4).
- `make freshness` runs on fixture data and computes what it says it does.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from makhzan_schemas.contracts import RawItem
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import IngestionStatus, ListingStatus, SourceType, StockSignal
from makhzan_schemas.models import IngestionRun, Listing, PriceObservation, Supplier
from sqlalchemy import insert, select

from worker import http as http_mod
from worker import robots as robots_mod
from worker.pipeline import run_source
from worker.sources.base import Page, SourceAdapter, SupplierInfo

SRC = "checklog-shop"


class Shop(SourceAdapter):
    """One page of scripted items: {external_id: (price_text, availability_text[, category])}."""

    source_id = SRC
    source_type = SourceType.SCRAPED
    supplier = SupplierInfo(slug=SRC, name="Check Log Shop")
    polite_delay = 0
    authoritative_categories = True

    def __init__(self, items: dict, out_of_stock_ids: list[str] | None = None):
        self.items = items
        self.out_of_stock_ids = out_of_stock_ids or []

    async def fetch_page(self, partition: str, page: int) -> Page:
        return Page(
            [
                RawItem(
                    source=SRC,
                    external_id=ext,
                    title=f"Arduino Uno R3 board {ext}",
                    price_text=spec[0],
                    availability_text=spec[1],
                    raw={"category": spec[2]} if len(spec) > 2 else {},
                )
                for ext, spec in self.items.items()
            ],
            has_more=False,
            out_of_stock_ids=self.out_of_stock_ids,
        )

    def category_for(self, raw: RawItem):
        category = (raw.raw or {}).get("category")
        return ("electronics", category) if category else None


async def _listing(external_id: str = "a1") -> Listing:
    async with SessionLocal() as s:
        return (
            await s.execute(select(Listing).where(Listing.external_id == external_id))
        ).scalar_one()


# --------------------------------------------------------------------------- #
# The check log
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_every_read_counts_and_only_a_move_is_a_change():
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}))
    first = await _listing()
    assert (first.checks, first.changes) == (1, 0)  # a first read is never a change
    assert first.first_checked_at is not None

    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}))
    again = await _listing()
    assert (again.checks, again.changes) == (2, 0)
    assert again.first_checked_at == first.first_checked_at  # set once

    await run_source(SRC, Shop({"a1": ("135 EGP", "In stock")}))
    await run_source(SRC, Shop({"a1": ("135 EGP", "Out of stock")}))
    moved = await _listing()
    assert (moved.checks, moved.changes) == (4, 2)


@pytest.mark.asyncio
async def test_a_limit_run_is_not_a_check():
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}))
    await run_source(SRC, Shop({"a1": ("150 EGP", "In stock")}), limit=10)

    listing = await _listing()
    assert listing.price == Decimal("150.00")  # it did update the listing
    assert (listing.checks, listing.changes) == (1, 0)

    # The change it saw unrecorded is counted by the next real read, as the
    # history row is: compared against the latest row, not the overwritten value.
    await run_source(SRC, Shop({"a1": ("150 EGP", "In stock")}))
    listing = await _listing()
    assert (listing.checks, listing.changes) == (2, 1)


@pytest.mark.asyncio
async def test_a_limit_run_never_starts_the_log():
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}), limit=10)
    listing = await _listing()
    assert (listing.checks, listing.changes, listing.first_checked_at) == (0, 0, None)


@pytest.mark.asyncio
async def test_out_of_stock_by_id_is_a_check_and_its_flip_a_change():
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}))
    await run_source(SRC, Shop({}, out_of_stock_ids=["a1"]))
    listing = await _listing()
    assert listing.stock_signal == StockSignal.OUT_OF_STOCK
    assert (listing.checks, listing.changes) == (2, 1)

    # Still out of stock: read again, no change.
    await run_source(SRC, Shop({}, out_of_stock_ids=["a1"]))
    listing = await _listing()
    assert (listing.checks, listing.changes) == (3, 1)

    await run_source(SRC, Shop({}, out_of_stock_ids=["a1"]), limit=10)
    assert (await _listing()).checks == 3


@pytest.mark.asyncio
async def test_coming_back_from_archive_at_the_same_values_is_not_a_change():
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock"), "b1": ("9 EGP", "In stock")}))
    await run_source(SRC, Shop({"b1": ("9 EGP", "In stock")}))  # a1 archived
    assert (await _listing()).status == ListingStatus.ARCHIVED
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock"), "b1": ("9 EGP", "In stock")}))

    listing = await _listing()
    assert listing.status == ListingStatus.ACTIVE
    assert (listing.checks, listing.changes) == (2, 0)


# --------------------------------------------------------------------------- #
# price_observations.via
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_every_row_today_is_the_sweeps_archiving_included():
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock"), "b1": ("9 EGP", "In stock")}))
    await run_source(SRC, Shop({"b1": ("9 EGP", "In stock")}))  # archives a1

    async with SessionLocal() as s:
        rows = (await s.execute(select(PriceObservation))).scalars().all()
    assert {r.available for r in rows} == {True, False}
    assert {r.via for r in rows} == {"sweep"}


@pytest.mark.asyncio
async def test_a_row_written_without_via_reads_sweep():
    """What a release older than the column writes while the migration runs."""
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}))
    listing = await _listing()
    async with SessionLocal() as s:
        await s.execute(
            insert(PriceObservation.__table__).values(
                id=uuid.uuid4(),
                listing_id=listing.id,
                observed_at=datetime.now(UTC),
                price=Decimal("1.00"),
                currency="EGP",
                stock_signal=StockSignal.IN_STOCK,
                in_stock=True,
            )
        )
        await s.commit()
        vias = (await s.execute(select(PriceObservation.via))).scalars().all()
    assert vias == ["sweep", "sweep"]


# --------------------------------------------------------------------------- #
# Category churn
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_category_moves_are_counted_on_stored_listings_only():
    run = await run_source(
        SRC,
        Shop({"a1": ("1 EGP", "In stock", "capacitors"), "b1": ("1 EGP", "In stock", "diodes")}),
    )
    # New listings getting their first category is not churn.
    assert run.stats["categories"] == {"set": 0, "moved": 0, "cleared": 0}

    run = await run_source(
        SRC,
        Shop({"a1": ("1 EGP", "In stock", "diodes"), "b1": ("1 EGP", "In stock", "diodes")}),
    )
    assert run.stats["categories"] == {"set": 0, "moved": 1, "cleared": 0}

    run = await run_source(
        SRC,
        Shop({"a1": ("1 EGP", "In stock", "capacitors"), "b1": ("1 EGP", "In stock")}),
        limit=10,
    )
    assert "categories" not in run.stats  # a test run speaks for nothing


# --------------------------------------------------------------------------- #
# Validators
# --------------------------------------------------------------------------- #


class _AllowAll:
    async def allowed(self, url, user_agent):
        return True

    async def crawl_delay(self, url, user_agent):
        return None


class _HttpShop(SourceAdapter):
    """Three pages: one with a weak ETag and Last-Modified, one with neither, one strong ETag."""

    source_id = "validator-shop"
    source_type = SourceType.SCRAPED
    supplier = SupplierInfo(slug="validator-shop", name="Validator Shop")
    polite_delay = 0
    base_url = "https://shop.test"

    HEADERS = {
        1: {"ETag": 'W/"abc"', "Last-Modified": "Wed, 11 Nov 2026 10:00:00 GMT"},
        2: {},
        3: {"ETag": '"xyz"'},
    }

    def _transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            page = int(request.url.path.rsplit("/", 1)[1])
            return httpx.Response(200, json={}, headers=self.HEADERS[page])

        return httpx.MockTransport(handler)

    async def fetch_page(self, partition: str, page: int) -> Page:
        async with httpx.AsyncClient(transport=self._transport()) as client:
            await http_mod.get_json(client, f"{self.base_url}/p/{page}")
        item = RawItem(
            source=self.source_id,
            external_id=f"x{page}",
            title=f"Part {page}",
            price_text="10 EGP",
            availability_text="In stock",
        )
        return Page([item], has_more=page < 3)


@pytest.mark.asyncio
async def test_validators_are_counted_per_host_and_kept_out_of_pacing(monkeypatch):
    monkeypatch.setattr(robots_mod, "ROBOTS", _AllowAll())
    monkeypatch.setattr(http_mod, "_NOT_BEFORE", {})
    run = await run_source(_HttpShop.source_id, _HttpShop())

    assert run.stats["validators"] == {
        "https://shop.test": {"responses": 3, "etag": 2, "etag_weak": 1, "last_modified": 1}
    }
    pacing = repr(run.stats["pacing"]).lower()
    for word in ("etag", "last_modified", "validator"):
        assert word not in pacing


def test_only_2xx_answers_are_counted():
    log = http_mod.RequestLog()
    log.note_validators("h", httpx.Response(304, headers={"ETag": '"a"'}))
    log.note_validators("h", httpx.Response(429, headers={"ETag": '"a"'}))
    assert log.validator_stats() == {}


# --------------------------------------------------------------------------- #
# make freshness
# --------------------------------------------------------------------------- #


def _freshness():
    path = Path(__file__).resolve().parents[3] / "scripts" / "freshness.py"
    spec = importlib.util.spec_from_file_location("makhzan_freshness", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cho_estimator_matches_its_formula():
    fresh = _freshness()
    assert fresh.cho_rate(10, 0, 7) == pytest.approx(-__import__("math").log(10.5 / 10.5) / 7)
    # 2 changes in 10 weekly checks: a bit above the naive 2/70 a day.
    rate = fresh.cho_rate(10, 2, 7)
    assert rate > 2 / 70
    assert fresh.cho_rate(0, 0, 7) is None


@pytest.mark.asyncio
async def test_freshness_report_on_fixture_data(capsys):
    fresh = _freshness()
    now = datetime.now(UTC)
    day = timedelta(days=1)
    supplier = Supplier(
        id=uuid.uuid4(), slug="fresh-shop", name="Fresh Shop", source_type=SourceType.SCRAPED
    )
    other = Supplier(
        id=uuid.uuid4(), slug="other-shop", name="Other Shop", source_type=SourceType.SCRAPED
    )

    def listing(ext, price, *, supplier=supplier, **kw):
        defaults = dict(
            id=uuid.uuid4(),
            supplier_id=supplier.id,
            source=supplier.slug,
            source_type=SourceType.SCRAPED,
            external_id=ext,
            title_en=f"Part {ext}",
            price=Decimal(price),
            stock_signal=StockSignal.IN_STOCK,
            status=ListingStatus.ACTIVE,
            last_verified_at=now - day,
            last_seen_at=now - day,
        )
        defaults.update(kw)
        return Listing(**defaults)

    cheap = listing("cheap", "20", checks=3, changes=0, first_checked_at=now - 15 * day)
    dear = listing("dear", "1500", checks=3, changes=1, first_checked_at=now - 15 * day)
    restock = listing(
        "restock", "100", stock_signal=StockSignal.OUT_OF_STOCK, last_verified_at=now - 30 * day
    )
    gone = listing("gone", "60", status=ListingStatus.ACTIVE)

    def obs(row, when, price, stock=StockSignal.IN_STOCK, available=True):
        return PriceObservation(
            listing_id=row.id,
            observed_at=when,
            price=Decimal(price),
            currency="EGP",
            stock_signal=stock,
            in_stock=available and stock == StockSignal.IN_STOCK,
            available=available,
        )

    def run(source, ago, stats, took=timedelta(hours=1)):
        return IngestionRun(
            source=source,
            source_type=SourceType.SCRAPED,
            status=IngestionStatus.SUCCESS,
            started_at=now - ago,
            finished_at=now - ago + took,
            stats=stats,
        )

    async with SessionLocal() as s:
        s.add_all([supplier, other])
        await s.flush()
        s.add_all([cheap, dear, restock, gone])
        await s.flush()
        s.add_all(
            [
                obs(cheap, now - 20 * day, "20"),
                obs(dear, now - 20 * day, "1400"),
                obs(dear, now - 2 * day, "1500"),  # a change in the window
                obs(restock, now - 40 * day, "100", StockSignal.OUT_OF_STOCK),
                obs(gone, now - 20 * day, "60"),
                obs(gone, now - 10 * day, "60", available=False),  # archived ...
                obs(gone, now - 1 * day, "60"),  # ... and back: a false archival
            ]
        )
        cycle = {
            "cycle_started_at": (now - 8 * day).isoformat(),
            "cycle_completed_at": (now - day).isoformat(),
            "cycle_seconds": 7 * 86400,
        }
        s.add_all(
            [
                run("fresh-shop", 8 * day, {"pacing": {"requests": 40}}),
                run("fresh-shop", 4 * day, {"requests": {"pages": 20, "robots": 1}}),
                run(
                    "fresh-shop",
                    day + timedelta(hours=1),
                    {
                        "pacing": {"requests": 39},
                        "cycle": cycle,
                        "validators": {
                            "https://fresh.test": {
                                "responses": 38,
                                "etag": 0,
                                "etag_weak": 0,
                                "last_modified": 19,
                            }
                        },
                        "categories": {"set": 0, "moved": 2, "cleared": 1},
                    },
                ),
                # A test run sends requests too, but is not part of any measure.
                run("fresh-shop", 3 * day, {"pacing": {"requests": 500}, "limit": 5}),
            ]
        )
        await s.commit()

    async with SessionLocal() as s:
        data = await fresh.collect(s, days=14)

    m1 = data["requests"]["fresh-shop"]
    assert m1["requests_window"] == 40 + 21 + 39
    assert m1["cycle_requests"] == 40 + 21 + 39  # every run overlaps the cycle
    assert m1["cycle_days"] == [7.0]
    assert m1["requests_max_day"] == 40

    assert data["staleness"]["fresh-shop"]["active"] == 4
    assert data["changes"]["fresh-shop"] == {"sweep": 1}
    log = data["check_log"]["fresh-shop"]
    assert (log["listings"], log["checks"], log["changes"]) == (2, 6, 1)
    assert log["delay_n"] == 1
    assert log["delay_p50"] == pytest.approx(7.0, abs=0.01)  # 14 days over 2 intervals

    assert data["false_archivals"]["fresh-shop"] == {"archived": 1, "back": 1, "back_within": 1}

    segments = {row["segment"]: row for row in data["segments"]}
    # restock was last read 30 days ago: not re-read in the window, so absent.
    assert segments["price >= 1,000"] == {
        "segment": "price >= 1,000",
        "n": 1,
        "price": 1,
        "stock": 0,
        "either": 1,
        "share_of_changes": 1.0,
    }
    assert segments["price < 50"]["either"] == 0
    assert "not in stock at baseline" not in segments
    assert segments["single supplier"]["n"] == 3

    assert data["validators"]["fresh-shop"]["last_modified"] == 19
    assert data["categories"]["fresh-shop"]["moved"] == 2

    excluded = await _collect_excluding(fresh, "fresh-shop")
    assert excluded["segments"] == []

    fresh.render(data)
    out = capsys.readouterr().out
    for section in ("M1 REQUESTS", "M2 COVERAGE", "M3 CHANGES", "M5 DETECTION", "M6 FALSE"):
        assert section in out


async def _collect_excluding(fresh, source):
    async with SessionLocal() as s:
        return await fresh.collect(s, days=14, exclude=[source])


def test_a_run_that_recorded_no_count_is_unknown_not_zero():
    from types import SimpleNamespace

    fresh = _freshness()
    assert fresh.run_requests({}) is None
    now = datetime.now(UTC)
    cycle = {
        "cycle_started_at": (now - timedelta(days=9)).isoformat(),
        "cycle_completed_at": (now - timedelta(days=3)).isoformat(),
        "cycle_seconds": 6 * 86400,
    }

    def run(days_ago, stats):
        started = now - timedelta(days=days_ago)
        return SimpleNamespace(
            source="s", started_at=started, finished_at=started + timedelta(hours=1), stats=stats
        )

    old = [run(8, {}), run(3, {"cycle": cycle})]
    entry = fresh.requests_and_cycles(old, now - timedelta(days=14), now)["s"]
    assert entry["cycle_requests"] is None

    mixed = [run(8, {"pacing": {"requests": 5}}), run(3, {"cycle": cycle})]
    entry = fresh.requests_and_cycles(mixed, now - timedelta(days=14), now)["s"]
    assert (entry["cycle_requests"], entry["cycle_requests_partial"]) == (5, True)
    assert fresh._count(5, True) == ">=5"


@pytest.mark.asyncio
async def test_freshness_report_on_an_empty_database(capsys):
    fresh = _freshness()
    async with SessionLocal() as s:
        data = await fresh.collect(s, days=14)
    fresh.render(data)
    assert "nothing archived in the window" in capsys.readouterr().out
