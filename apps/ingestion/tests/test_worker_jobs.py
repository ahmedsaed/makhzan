"""The worker's jobs: one per source a day, and a shared rebuild after them.

One cron job used to crawl every source and then rebuild products, so one slow
host held the whole job and the rebuild ran only if the job beat its timeout.
These pin the split: each source is its own job with its own timeout, a source
is never run twice at once, and every source job, however it ends, leads to a
rebuild that sources finishing close together share.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from worker import main


class FakeRedis:
    """arq's `enqueue_job`, including its refusal of a job id already taken."""

    def __init__(self) -> None:
        self.jobs: dict[str, tuple[str, tuple, dict]] = {}

    async def enqueue_job(self, function, *args, _job_id=None, **kwargs):
        job_id = _job_id or f"anon-{len(self.jobs)}"
        if job_id in self.jobs:
            return None
        self.jobs[job_id] = (function, args, kwargs)
        return SimpleNamespace(job_id=job_id)

    def named(self, function: str) -> list[str]:
        return [job_id for job_id, (f, _, _) in self.jobs.items() if f == function]


def _run(source_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        status="success",
        items_seen=1,
        items_created=1,
        items_updated=0,
        items_for_review=0,
        items_failed=0,
        stats={},
    )


@pytest.fixture
def worker(monkeypatch):
    """The worker's module with two enabled sources and no real crawling."""
    sources = [SimpleNamespace(source_id="shop-a"), SimpleNamespace(source_id="shop-b")]

    async def no_load():
        return None

    async def run_source(source_id, adapter, limit=None):
        return _run(source_id)

    monkeypatch.setattr(main, "load_adapters", no_load)
    monkeypatch.setattr(main, "all_enabled", lambda: sources)
    monkeypatch.setattr(main, "get", lambda source_id: None)

    monkeypatch.setattr(main, "_run_source", run_source)
    monkeypatch.setattr(main, "_SOURCE_LOCKS", {})
    monkeypatch.setattr(main, "CRAWL_ENABLED", True)
    return main


async def test_the_daily_cron_queues_one_job_per_source_and_day(worker):
    redis = FakeRedis()
    queued = await worker.refresh_all({"redis": redis})

    today = datetime.now(UTC).date().isoformat()
    assert sorted(redis.named("crawl_source")) == [
        f"crawl:shop-a:{today}",
        f"crawl:shop-b:{today}",
    ]
    assert [q["status"] for q in queued] == ["queued", "queued"]

    # Fired twice in a day (a restart at the cron minute): nothing is queued twice.
    again = await worker.refresh_all({"redis": redis})
    assert [q["status"] for q in again] == ["already queued", "already queued"]
    assert len(redis.jobs) == 2


async def test_nothing_is_queued_while_the_crawl_is_off(worker, monkeypatch):
    monkeypatch.setattr(worker, "CRAWL_ENABLED", False)
    redis = FakeRedis()
    assert (await worker.refresh_all({"redis": redis}))[0]["status"] == "skipped"
    assert redis.jobs == {}


async def test_a_finished_source_asks_for_a_rebuild(worker):
    redis = FakeRedis()
    summary = await worker.crawl_source({"redis": redis}, "shop-a")
    assert summary["source"] == "shop-a"
    (job_id,) = redis.named("rebuild_and_reindex")
    _, _, kwargs = redis.jobs[job_id]
    assert kwargs["_defer_until"] > datetime.now(UTC)


@pytest.mark.parametrize("ending", [RuntimeError("host down"), asyncio.CancelledError()])
async def test_a_source_that_fails_or_times_out_still_leads_to_a_rebuild(
    worker, monkeypatch, ending
):
    """arq cancels a job at its timeout. What the run committed before that
    must still reach search, so the rebuild is asked for on the way out."""

    async def broken(source_id, adapter, limit=None):
        raise ending

    monkeypatch.setattr(worker, "_run_source", broken)
    redis = FakeRedis()
    with pytest.raises(type(ending)):
        await worker.crawl_source({"redis": redis}, "shop-a")
    assert len(redis.named("rebuild_and_reindex")) == 1


async def test_sources_finishing_close_together_share_one_rebuild(worker):
    redis = FakeRedis()
    await worker.crawl_source({"redis": redis}, "shop-a")
    await worker.crawl_source({"redis": redis}, "shop-b")
    assert len(redis.named("rebuild_and_reindex")) == 1


def test_a_later_finish_gets_the_next_windows_rebuild():
    """Deduplicated per window, never per day: one that finishes after a
    rebuild ran gets its own, rather than being refused as a duplicate."""
    first, first_at = main.rebuild_job_id(datetime(2026, 11, 9, 3, 1, tzinfo=UTC))
    same, _ = main.rebuild_job_id(datetime(2026, 11, 9, 3, 9, tzinfo=UTC))
    later, later_at = main.rebuild_job_id(datetime(2026, 11, 9, 3, 11, tzinfo=UTC))
    assert first == same != later
    assert first_at <= datetime(2026, 11, 9, 3, 10, tzinfo=UTC) < later_at


async def test_two_runs_of_one_source_never_overlap_and_other_sources_carry_on(worker, monkeypatch):
    """Cursors, cycles and the pace gate assume one run of a source at a time,
    and a slow host must not hold the others."""
    release = asyncio.Event()
    started: list[str] = []

    async def slow_a(source_id, adapter, limit=None):
        started.append(source_id)
        if source_id == "shop-a":
            await release.wait()
        return _run(source_id)

    monkeypatch.setattr(worker, "_run_source", slow_a)
    redis = FakeRedis()
    ctx = {"redis": redis}

    first = asyncio.create_task(worker.crawl_source(ctx, "shop-a"))
    await asyncio.sleep(0)
    # A run of shop-a enqueued by hand while the daily one is going.
    assert (await worker.run_source(ctx, "shop-a"))["status"] == "skipped"
    # shop-b is not held by shop-a.
    assert (await worker.crawl_source(ctx, "shop-b"))["source"] == "shop-b"

    release.set()
    assert (await first)["source"] == "shop-a"
    assert started == ["shop-a", "shop-b"]


async def test_rebuilds_never_interleave(monkeypatch):
    events: list[str] = []

    async def rebuild(session):
        events.append("rebuild start")
        await asyncio.sleep(0)
        events.append("rebuild end")

    async def reindex(session, client):
        events.append("reindex")

    async def retire(session, today):
        events.append("retire")
        return None

    monkeypatch.setattr(main, "rebuild_products", rebuild)
    monkeypatch.setattr(main, "reindex_all", reindex)
    monkeypatch.setattr(main, "retire_redirects_daily", retire)
    monkeypatch.setattr(main, "get_client", lambda: None)
    monkeypatch.setattr(main, "_REBUILD_LOCK", asyncio.Lock())

    await asyncio.gather(main.rebuild_and_reindex({}), main.rebuild_and_reindex({}))
    assert events == ["rebuild start", "rebuild end", "reindex", "retire"] * 2


async def test_redirects_are_retired_once_a_day(monkeypatch):
    """The first rebuild of a day retires unused redirects; later ones that day do not."""
    from makhzan_schemas.db import SessionLocal
    from makhzan_schemas.models import WorkerState

    calls: list[int] = []

    async def retire(session, **kwargs):
        calls.append(1)
        return {"merged_products": 0, "product_redirects": 0}

    monkeypatch.setattr(main, "retire_unused_redirects", retire)
    day = datetime(2027, 11, 9, tzinfo=UTC).date()
    async with SessionLocal() as session:
        await session.execute(
            WorkerState.__table__.delete().where(WorkerState.key == main.RETIRED_STATE_KEY)
        )
        await session.commit()
        assert await main.retire_redirects_daily(session, day) is not None
        assert await main.retire_redirects_daily(session, day) is None
        next_day = datetime(2027, 11, 10, tzinfo=UTC).date()
        assert await main.retire_redirects_daily(session, next_day) is not None
    assert len(calls) == 2


def test_the_worker_runs_every_source_at_once_and_still_has_room_to_rebuild():
    assert main.WorkerSettings.max_jobs == main.MAX_CONCURRENT_SOURCES + 1
    names = {
        getattr(f, "name", getattr(f, "__name__", None)) for f in main.WorkerSettings.functions
    }
    assert {"crawl_source", "rebuild_and_reindex", "run_source", "run_partition"} <= names
