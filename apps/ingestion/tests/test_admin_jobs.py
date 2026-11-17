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
