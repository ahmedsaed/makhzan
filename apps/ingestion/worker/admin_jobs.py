"""The jobs the admin dashboard queues, run by the worker (`admin_job`).

The dashboard (apps/ingestion/admin) never crawls, probes or regroups in its
own process: it writes an `admin_actions` row with `status = 'queued'` and
queues `admin_job(action_id)` here, in the one worker process that owns the
per-source locks, the pace gate and the signing key. The job marks the row
`running`, does the work through the same code the CLI runs, and stores the
outcome in `result` (or `error`) with `done`/`failed`. The page polls the row.

- `job.run_limit` {source, limit}: an ephemeral run, as `make ingest
  SOURCE=x LIMIT=n`: `worker.main.run_source(limit=n)`, cursors untouched,
  nothing archived, no history, under the source's lock (refused while a run
  of it is going). Works on a paused source: it is how one is tried.
- `job.probe` {source}: `worker.probe` for that one source, paused or
  disabled included, with the crawler's own client, robots.txt asked first
  and obeyed, `probe.MIN_GAP` between requests to the host, and every
  request through `worker.http.take_turn`, the gate the crawl uses in this
  process (its pace, Retry-After and slowdown). A host with a Retry-After
  pending or slowed after errors is refused, not asked. Held under the
  source's lock, so it never overlaps a run of the same shop.
- `job.regroup_dry_run` {}: `rebuild_products(dry_run=True, reidentify=True)`,
  what `make regroup-dry-run` prints: every listing read, nothing kept (the
  transaction is rolled back), the products lock held while it runs.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.grouping import describe, rebuild_products
from makhzan_schemas.models import AdminAction

log = logging.getLogger(__name__)

RUN_LIMIT = "job.run_limit"
PROBE = "job.probe"
REGROUP_DRY_RUN = "job.regroup_dry_run"
JOBS = (RUN_LIMIT, PROBE, REGROUP_DRY_RUN)

#: The largest `limit` the dashboard may ask for: a quick look, not a sweep.
MAX_LIMIT = 200


#: A row still `queued` after this long, whose arq job is gone (the queue was
#: flushed, or the enqueue never landed), is marked failed: nothing will run it.
LOST_AFTER = timedelta(minutes=10)


async def expire_lost(session, exists: Callable[[str], Awaitable[bool]]) -> int:
    """Mark queued rows whose arq job no longer exists as failed (flushed, not committed).

    `exists(key)` asks Redis for a key; arq keeps `arq:job:<id>` while a job is
    queued or deferred and `arq:in-progress:<id>` while it runs.
    """
    from sqlalchemy import select

    cutoff = datetime.now(timezone.utc) - LOST_AFTER
    rows = list(
        await session.scalars(
            select(AdminAction).where(
                AdminAction.status == "queued", AdminAction.created_at < cutoff
            )
        )
    )
    lost = 0
    for row in rows:
        key = job_id(row.id)
        if await exists(f"arq:job:{key}") or await exists(f"arq:in-progress:{key}"):
            continue
        row.status = "failed"
        row.error = "lost: the worker's queue no longer holds this job"
        row.finished_at = datetime.now(timezone.utc)
        lost += 1
    await session.flush()
    return lost


def job_id(action_id: int) -> str:
    """The arq job id for an action: one job per row, however often it is asked for."""
    return f"admin:{action_id}"


def _jsonable(value):
    return json.loads(json.dumps(value, default=str))


async def _set(action_id: int, **values) -> None:
    async with SessionLocal() as session:
        row = await session.get(AdminAction, action_id)
        if row is not None:
            for key, value in values.items():
                setattr(row, key, value)
            await session.commit()


async def _run_limit(ctx: dict, source_id: str, limit: int) -> dict:
    from worker import main
    from worker.sources.registry import load_adapters

    if not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    await load_adapters()
    summary = await main.run_source(ctx, source_id, limit=limit)
    if summary.get("status") == "skipped":
        raise RuntimeError(summary.get("reason") or "skipped")
    return summary


async def _probe(source_id: str) -> dict:
    from worker import main
    from worker import probe as probing
    from worker.sources.registry import get, load_adapters

    errors = await load_adapters()
    if source_id in errors:
        raise RuntimeError(f"{source_id} does not load: {errors[source_id]}")
    sites_path = probing.default_sites_file()
    sites = probing.read_sites(sites_path) if sites_path and sites_path.exists() else {}
    target = probing.target_for(get(source_id), sites)
    if target is None:
        raise RuntimeError(f"{source_id} has no URL to probe")
    # The crawl's own gate, in this process: a host holding us off is not asked.
    if why := probing.refusal(target.url):
        raise RuntimeError(why)
    lock = main._SOURCE_LOCKS.setdefault(source_id, asyncio.Lock())
    if lock.locked():
        raise RuntimeError("a run of it is in progress; probe it once that ends")
    async with lock:
        rows, notes = await probing.probe([target])
    cells = {
        name: {
            "text": cell.text(),
            "status": cell.status,
            "http_version": cell.http_version,
            "error": cell.error,
            "note": cell.note,
        }
        for name, cell in rows[0].cells.items()
    }
    return {"url": target.url, "identity": target.identity, "cells": cells, "notes": notes}


async def _regroup_dry_run() -> dict:
    async with SessionLocal() as session:
        stats = await rebuild_products(session, dry_run=True, reidentify=True)
    return {"stats": _jsonable(stats), "line": "would regroup: " + describe(stats)}


async def close_interrupted_jobs(session) -> int:
    """At worker startup: a job left `running` was cut off by the restart. Commits.

    Like `close_interrupted_runs`, and for the same reason: nothing of this
    worker's is running yet. Queued ones stay queued; arq still holds them.
    """
    from sqlalchemy import update

    result = await session.execute(
        update(AdminAction)
        .where(AdminAction.status == "running")
        .values(
            status="failed",
            error="interrupted: the worker restarted during this job",
            finished_at=datetime.now(timezone.utc),
        )
    )
    await session.commit()
    return result.rowcount or 0


async def admin_job(ctx: dict, action_id: int) -> str:
    """Arq task: run the dashboard's job `action_id` and record how it went."""
    async with SessionLocal() as session:
        row = await session.get(AdminAction, action_id)
        if row is None or row.status != "queued":
            return "nothing to do"
        action, target, detail = row.action, row.target, dict(row.detail or {})
        row.status, row.started_at = "running", datetime.now(timezone.utc)
        await session.commit()
    finished = False
    try:
        if action == RUN_LIMIT:
            result = await _run_limit(ctx, target, int(detail.get("limit") or 0))
        elif action == PROBE:
            result = await _probe(target)
        elif action == REGROUP_DRY_RUN:
            result = await _regroup_dry_run()
        else:
            raise ValueError(f"not a dashboard job: {action}")
    except Exception as exc:  # noqa: BLE001 — recorded on the row for the page to show
        log.exception("admin job %s (%s) failed", action_id, action)
        await _set(
            action_id,
            status="failed",
            error=f"{type(exc).__name__}: {exc}"[:2000],
            finished_at=datetime.now(timezone.utc),
        )
        finished = True
        return "failed"
    else:
        await _set(
            action_id,
            status="done",
            result=_jsonable(result),
            finished_at=datetime.now(timezone.utc),
        )
        finished = True
        return "done"
    finally:
        if not finished:
            # Cancelled: arq's job timeout, or the worker stopping. Shielded, so
            # the row is not left `running` for the page to poll forever.
            await asyncio.shield(
                _set(
                    action_id,
                    status="failed",
                    error="cancelled: the job timed out or the worker stopped",
                    finished_at=datetime.now(timezone.utc),
                )
            )
