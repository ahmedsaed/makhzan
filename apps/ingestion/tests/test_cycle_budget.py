"""Adaptive pacing: a source with `target_cycle_days` plans each run's pages.

A fixed `max_pages_per_run` makes a cycle stretch as the shop grows. With a
target, each run's budget is what the cycle still owes (from the last completed
cycle's size) over the days it has left, with `max_pages_per_run` as a hard
ceiling the budget never exceeds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from makhzan_schemas.contracts import RawItem
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import IngestionStatus, SourceType
from makhzan_schemas.models import IngestionRun, Source, SourceCursor
from worker import pipeline
from worker.pipeline import run_source
from worker.sources.base import Page, SourceAdapter, SupplierInfo
from worker.sources.registry import build_adapter

SRC = "budget-shop"


class Shop(SourceAdapter):
    source_id = SRC
    source_type = SourceType.SCRAPED
    supplier = SupplierInfo(slug=SRC, name="Budget Shop")
    polite_delay = 0

    def __init__(self, sizes, *, max_pages_per_run=None, target_cycle_days=None):
        self.sizes = sizes
        self.max_pages_per_run = max_pages_per_run
        self.target_cycle_days = target_cycle_days
        self.fetched: list[tuple[str, int]] = []

    def partitions(self):
        return list(self.sizes)

    async def fetch_page(self, partition, page):
        self.fetched.append((partition, page))
        item = RawItem(
            source=SRC,
            external_id=f"{partition}-{page}",
            title=f"Item {partition} {page}",
            price_text="10 EGP",
            availability_text="In stock",
        )
        return Page([item], has_more=page < self.sizes[partition])


async def test_a_completed_cycle_records_how_many_pages_it_read():
    """The size the next cycle is planned from, summed over every run of it."""
    adapter = Shop({"a": 2, "b": 7}, max_pages_per_run=3)
    cycle = {}
    for _ in range(10):
        run = await run_source(SRC, adapter)
        if cycle := run.stats.get("cycle"):
            break
    assert cycle["cycle_pages"] == len(adapter.fetched) == 9


async def test_a_limited_test_run_is_not_counted_in_the_cycle():
    await run_source(SRC, Shop({"a": 3}), limit=1)
    run = await run_source(SRC, Shop({"a": 3}))
    assert run.stats["cycle"]["cycle_pages"] == 3


async def test_without_a_target_nothing_changes():
    adapter = Shop({"a": 5, "b": 5}, max_pages_per_run=2)
    run = await run_source(SRC, adapter)
    assert "budget" not in run.stats
    assert len(adapter.fetched) == 4  # the per-partition cap, as before


async def test_before_any_cycle_the_ceiling_caps_the_whole_run():
    """With a target, max_pages_per_run caps the run's total, not each
    partition's: the most the owner approved for a run."""
    adapter = Shop({"a": 5, "b": 5}, max_pages_per_run=4, target_cycle_days=7)
    run = await run_source(SRC, adapter)
    assert len(adapter.fetched) == 4
    assert run.stats["budget"]["pages"] == 4
    assert "no completed cycle" in run.stats["budget"]["basis"]


async def _history(previous_pages: int, *, days_in: float, read: int) -> None:
    """A completed cycle of `previous_pages`, and a current one `days_in` days
    old that has read `read` pages so far."""
    now = datetime.now(UTC)
    started = now - timedelta(days=days_in)
    async with SessionLocal() as s:
        s.add(
            IngestionRun(
                source=SRC,
                source_type=SourceType.SCRAPED,
                status=IngestionStatus.SUCCESS,
                started_at=started - timedelta(days=1),
                finished_at=started - timedelta(hours=20),
                stats={"cycle": {"cycle_pages": previous_pages}, "requests": {"pages": 10}},
            )
        )
        s.add(
            IngestionRun(
                source=SRC,
                source_type=SourceType.SCRAPED,
                status=IngestionStatus.SUCCESS,
                started_at=started + timedelta(minutes=1),
                finished_at=started + timedelta(hours=1),
                stats={"requests": {"pages": read}},
            )
        )
        s.add(SourceCursor(source=SRC, partition_key="a", cycle_started_at=started, next_page=2))
        await s.commit()


async def _budget(adapter) -> dict:
    async with SessionLocal() as s:
        return await pipeline._page_budget(s, adapter)


async def test_the_budget_spreads_what_the_cycle_still_owes_over_the_days_left():
    # 70 pages last cycle, 2 days into a 7-day target, 20 read: 50 over 5 days.
    await _history(70, days_in=2, read=20)
    budget = await _budget(Shop({"a": 1}, max_pages_per_run=30, target_cycle_days=7))
    assert budget["pages"] == 10
    assert budget["ceiling_limited"] is False
    assert budget["projected_cycle_days"] == pytest.approx(7.0, abs=0.1)


async def test_a_grown_shop_gets_more_pages_a_run():
    await _history(140, days_in=2, read=20)
    budget = await _budget(Shop({"a": 1}, max_pages_per_run=30, target_cycle_days=7))
    assert budget["pages"] == 24  # 120 owed over 5 days


async def test_the_ceiling_is_never_exceeded_and_says_when_it_binds():
    await _history(70, days_in=2, read=20)
    budget = await _budget(Shop({"a": 1}, max_pages_per_run=6, target_cycle_days=7))
    assert budget["pages"] == 6
    assert budget["planned"] == 10
    assert budget["ceiling_limited"] is True
    # 50 pages left at 6 a day: the cycle will run past its target, and says so.
    assert budget["projected_cycle_days"] == pytest.approx(2 + 9, abs=0.1)


async def test_a_cycle_ahead_of_schedule_still_moves_at_the_floor():
    await _history(70, days_in=1, read=69)
    budget = await _budget(Shop({"a": 1}, target_cycle_days=7))
    assert budget["planned"] == 1
    assert budget["pages"] == 5  # half a day's even share of 70 over 7


async def test_a_late_cycle_is_owed_everything_left_in_one_run():
    await _history(70, days_in=9, read=40)
    budget = await _budget(Shop({"a": 1}, max_pages_per_run=100, target_cycle_days=7))
    assert budget["pages"] == 30


async def test_make_status_shows_the_target_the_projection_and_a_binding_ceiling(capsys):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "scripts" / "status.py"
    spec = importlib.util.spec_from_file_location("makhzan_status", path)
    status = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(status)

    await _history(70, days_in=2, read=20)
    await run_source(SRC, Shop({"a": 100}, max_pages_per_run=6, target_cycle_days=7))
    async with SessionLocal() as s:
        await status.cycle_budget(s, None)

    out = capsys.readouterr().out
    assert "CYCLE TARGETS" in out
    assert "target 7d" in out and "budget 6 pages/run" in out
    assert "projected" in out and "ceiling-limited" in out


def test_the_target_is_read_from_a_source_config():
    def row(config):
        return Source(
            source_id="shop-a",
            adapter="woocommerce",
            base_url="https://shop-a.test",
            enabled=True,
            supplier={"slug": "shop-a", "name": "Shop A"},
            config=config,
        )

    assert build_adapter(row({"target_cycle_days": 7})).target_cycle_days == 7.0
    assert build_adapter(row({})).target_cycle_days is None
    for bad in (0, -1, "7", True):
        with pytest.raises(ValueError, match="target_cycle_days"):
            build_adapter(row({"target_cycle_days": bad}))
