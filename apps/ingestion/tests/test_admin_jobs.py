"""The admin dashboard's jobs, as the worker runs them (worker/admin_jobs.py).

The dashboard writes a queued `admin_actions` row; `admin_job` marks it
running, does the work through the CLI's own code, and records the outcome.
"""

from __future__ import annotations

import asyncio

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.models import AdminAction, Listing, Product, Source
from sqlalchemy import func, select
from test_pipeline import SRC, StubAdapter, _listings
from worker import admin_jobs, main
from worker import probe as probing
from worker.pipeline import run_source
from worker.sources import registry


async def _job(action: str, target: str | None = None, detail: dict | None = None) -> int:
    row = AdminAction(
        actor="owner", action=action, target=target, detail=detail or {}, status="queued"
    )
    async with SessionLocal() as session:
        session.add(row)
        await session.commit()
    return row.id


async def _row(action_id: int) -> AdminAction:
    async with SessionLocal() as session:
        return await session.get(AdminAction, action_id)


async def _counts() -> tuple[int, int]:
    async with SessionLocal() as session:
        products = await session.scalar(select(func.count()).select_from(Product))
        assigned = await session.scalar(
            select(func.count()).select_from(Listing).where(Listing.product_id.is_not(None))
        )
    return products, assigned


async def test_the_regroup_dry_run_reports_counts_and_writes_nothing():
    await run_source(SRC, StubAdapter())  # five listings, never grouped
    before = await _counts()
    action_id = await _job(admin_jobs.REGROUP_DRY_RUN)
    assert await admin_jobs.admin_job({}, action_id) == "done"
    row = await _row(action_id)
    assert row.status == "done" and row.started_at and row.finished_at
    assert row.result["stats"]["products"] == 5
    assert row.result["stats"]["created"] == 5
    assert row.result["line"].startswith("would regroup: products: 5 listed")
    assert await _counts() == before == (0, 0)


async def test_a_job_runs_once():
    action_id = await _job(admin_jobs.REGROUP_DRY_RUN)
    assert await admin_jobs.admin_job({}, action_id) == "done"
    assert await admin_jobs.admin_job({}, action_id) == "nothing to do"


def _registered(monkeypatch, adapter) -> None:
    async def load(session=None):
        registry._REGISTRY.clear()
        registry._REGISTRY[adapter.source_id] = adapter
        return {}

    monkeypatch.setattr(registry, "load_adapters", load)
    monkeypatch.setattr(main, "get", lambda source_id: registry._REGISTRY[source_id])
    monkeypatch.setattr(main, "_SOURCE_LOCKS", {})


async def test_run_now_is_an_ephemeral_limit_run(monkeypatch):
    adapter = StubAdapter()
    _registered(monkeypatch, adapter)
    action_id = await _job(admin_jobs.RUN_LIMIT, SRC, {"limit": 3})
    assert await admin_jobs.admin_job({}, action_id) == "done"
    row = await _row(action_id)
    assert (row.result["status"], row.result["seen"]) == ("success", 3)
    assert len(await _listings()) == 3


async def test_run_now_refuses_a_limit_out_of_bounds(monkeypatch):
    _registered(monkeypatch, StubAdapter())
    action_id = await _job(admin_jobs.RUN_LIMIT, SRC, {"limit": admin_jobs.MAX_LIMIT + 1})
    assert await admin_jobs.admin_job({}, action_id) == "failed"
    assert "limit must be between" in (await _row(action_id)).error


async def test_the_probe_asks_one_shop_disabled_or_not_and_records_each_cell(monkeypatch):
    adapter = StubAdapter()
    adapter.enabled = False
    adapter.base_url = "https://shop.test"
    adapter.identity = "browser"
    _registered(monkeypatch, adapter)
    asked: list[str] = []

    async def fake_probe(targets, **kw):
        asked.extend(t.url for t in targets)
        await probing.take_turn("https://shop.test")  # one request through the gate
        row = probing.Row(targets[0])
        row.cells = {
            "robots": probing.Cell(status=200, http_version="HTTP/1.1"),
            "browser": probing.Cell(status=403, http_version="HTTP/1.1"),
            "makhzanbot": probing.Cell(status=200, http_version="HTTP/1.1"),
            "signed": probing.Cell(),
        }
        return [row], ["signed skipped: no key"]

    monkeypatch.setattr(probing, "probe", fake_probe)
    action_id = await _job(admin_jobs.PROBE, SRC)
    assert await admin_jobs.admin_job({}, action_id) == "done"
    result = (await _row(action_id)).result
    assert asked == ["https://shop.test/"]
    assert result["cells"]["browser"]["status"] == 403
    assert result["cells"]["makhzanbot"]["text"] == "200 h1.1"
    assert result["notes"] == ["signed skipped: no key"]
    # Its requests, measured at the crawl's gate, kept on the row (no run carries them).
    assert result["pacing"]["requests"] == 1


async def test_a_recorded_retry_after_refuses_the_probe(monkeypatch):
    import time

    from worker import http as http_mod

    adapter = StubAdapter()
    adapter.base_url = "https://shop.test"
    _registered(monkeypatch, adapter)
    probed: list = []

    async def never(targets, **kw):
        probed.append(targets)
        return [], []

    monkeypatch.setattr(probing, "probe", never)
    http_mod._NOT_BEFORE["https://shop.test"] = time.monotonic() + 300
    action_id = await _job(admin_jobs.PROBE, SRC)
    assert await admin_jobs.admin_job({}, action_id) == "failed"
    assert "Retry-After" in (await _row(action_id)).error
    assert probed == []


async def test_the_probe_waits_for_no_run_of_the_same_shop(monkeypatch):
    adapter = StubAdapter()
    adapter.base_url = "https://shop.test"
    _registered(monkeypatch, adapter)
    lock = main._SOURCE_LOCKS.setdefault(SRC, asyncio.Lock())
    async with lock:
        action_id = await _job(admin_jobs.PROBE, SRC)
        assert await admin_jobs.admin_job({}, action_id) == "failed"
    assert "a run of it is in progress" in (await _row(action_id)).error


async def test_a_job_cut_off_by_a_restart_is_closed_at_startup():
    action_id = await _job(admin_jobs.REGROUP_DRY_RUN)
    async with SessionLocal() as session:
        row = await session.get(AdminAction, action_id)
        row.status = "running"
        await session.commit()
        assert await admin_jobs.close_interrupted_jobs(session) == 1
    row = await _row(action_id)
    assert row.status == "failed" and "interrupted" in row.error


def test_the_worker_registers_the_job():
    names = {getattr(f, "name", None) for f in main.WorkerSettings.functions}
    assert "admin_job" in names


async def test_an_unknown_source_fails_the_probe_cleanly(monkeypatch):
    async with SessionLocal() as session:
        session.add(
            Source(source_id="other", adapter="fixture", supplier={"slug": "o", "name": "o"})
        )
        await session.commit()
    _registered(monkeypatch, StubAdapter())
    action_id = await _job(admin_jobs.PROBE, "missing")
    assert await admin_jobs.admin_job({}, action_id) == "failed"
    assert (await _row(action_id)).error.startswith("KeyError")


async def test_a_cancelled_job_is_marked_failed_not_left_running(monkeypatch):
    """arq cancels a job at its timeout; the page must not poll a `running` row forever."""
    started = asyncio.Event()

    async def slow():
        started.set()
        await asyncio.sleep(3600)

    monkeypatch.setattr(admin_jobs, "_regroup_dry_run", slow)
    action_id = await _job(admin_jobs.REGROUP_DRY_RUN)
    task = asyncio.create_task(admin_jobs.admin_job({}, action_id))
    await started.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    row = await _row(action_id)
    assert row.status == "failed" and row.error.startswith("cancelled")


async def test_a_cancel_during_the_done_write_does_not_turn_it_into_failed(monkeypatch):
    real_set = admin_jobs._set
    writing = asyncio.Event()

    async def slow_set(action_id, **values):
        if values.get("status") == "done":
            writing.set()
            await asyncio.sleep(0.05)
        await real_set(action_id, **values)

    async def quick():
        return {"stats": {}, "line": "would regroup"}

    monkeypatch.setattr(admin_jobs, "_set", slow_set)
    monkeypatch.setattr(admin_jobs, "_regroup_dry_run", quick)
    action_id = await _job(admin_jobs.REGROUP_DRY_RUN)
    task = asyncio.create_task(admin_jobs.admin_job({}, action_id))
    await writing.wait()
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await asyncio.sleep(0.1)  # the shielded write finishes
    assert (await _row(action_id)).status == "done"


async def test_a_result_that_cannot_be_recorded_still_marks_the_job_failed(monkeypatch):
    real_set = admin_jobs._set

    async def broken_done(action_id, **values):
        if values.get("status") == "done":
            raise RuntimeError("result too odd to store")
        await real_set(action_id, **values)

    async def quick():
        return {"stats": {}, "line": "would regroup"}

    monkeypatch.setattr(admin_jobs, "_set", broken_done)
    monkeypatch.setattr(admin_jobs, "_regroup_dry_run", quick)
    action_id = await _job(admin_jobs.REGROUP_DRY_RUN)
    assert await admin_jobs.admin_job({}, action_id) == "failed"
    row = await _row(action_id)
    assert row.status == "failed"
    assert row.error.startswith("could not record the result: RuntimeError")


async def test_a_queued_job_the_queue_lost_is_marked_failed():
    from datetime import UTC, datetime

    lost_id = await _job(admin_jobs.REGROUP_DRY_RUN)
    waiting_id = await _job(admin_jobs.REGROUP_DRY_RUN)
    fresh_id = await _job(admin_jobs.REGROUP_DRY_RUN)
    async with SessionLocal() as session:
        for action_id in (lost_id, waiting_id):
            row = await session.get(AdminAction, action_id)
            row.created_at = datetime.now(UTC) - admin_jobs.LOST_AFTER * 2
        await session.commit()

    async def exists(key: str) -> bool:
        return key == f"arq:job:{admin_jobs.job_id(waiting_id)}"

    async with SessionLocal() as session:
        assert await admin_jobs.expire_lost(session, exists) == 1
        await session.commit()
    assert (await _row(lost_id)).status == "failed"
    assert (await _row(waiting_id)).status == "queued"
    assert (await _row(fresh_id)).status == "queued"
