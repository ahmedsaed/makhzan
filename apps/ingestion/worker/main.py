"""makhzan ingestion worker entrypoint (Arq).

Runs source adapters (scrapers / manual imports / portal syncs), normalizes
their output into Listings, and routes low-confidence items to a review queue.

Scheduling: a daily cron (`refresh_all`) re-scrapes every enabled source so
prices/stock stay fresh and vanished products get archived. Idempotent upserts
mean re-runs update in place. Run the worker:  arq worker.main.WorkerSettings
"""

import asyncio
import os
from datetime import datetime, timezone

from arq import cron
from arq.connections import RedisSettings
from makhzan_schemas import crawl
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import IngestionStatus
from makhzan_schemas.grouping import rebuild_products
from makhzan_schemas.models import IngestionRun
from sqlalchemy import update

from worker.indexer import get_client, reindex_all
from worker.pipeline import run_partition as _run_partition
from worker.pipeline import run_source as _run_source
from worker.retire_redirects import retire_unused_redirects
from worker.sources.registry import all_enabled, get, load_adapters

#: Hour of day (UTC) for the daily full refresh. Defined beside the API's reading
#: of it, which publishes when the next run starts.
REFRESH_HOUR = crawl.REFRESH_HOUR

#: Off pauses the daily sweep without stopping the worker. Stopping the container
#: would also pause it, but deploy.sh runs `up -d` and would quietly restart it.
#: Progress is durable and archiving is cycle-gated, so a pause loses nothing —
#: the next sweep resumes where the last one stopped. Manual run_source still works.
CRAWL_ENABLED = crawl.crawl_enabled()

#: How many sources to scrape concurrently. Each source hits a different host
#: with an independent rate limit, so concurrency doesn't stack on any one
#: supplier — this caps our total outbound load (and DB connections in use),
#: not per-host politeness (that's SourceAdapter.polite_delay). Keep it below the
#: DB pool ceiling (pool_size + max_overflow), since each run holds one session.
MAX_CONCURRENT_SOURCES = int(os.getenv("MAX_CONCURRENT_SOURCES", "8"))

#: How long the daily refresh may run before arq cancels it. arq's own default
#: is 300 s, and the refresh was being killed at that mark every day: a source
#: of many small categories needs longer than five minutes at a polite pace, so
#: its run was cut off mid-sweep, and the product rebuild and reindex at the end
#: of the job never ran. Pages are durable, so nothing was lost, but search went
#: stale. Hours, not minutes: the slowest source decides, and a cycle's first
#: run adds its once-a-cycle requests.
JOB_TIMEOUT = int(os.getenv("REFRESH_TIMEOUT_SECONDS", str(6 * 3600)))


async def startup(ctx: dict) -> None:
    await load_adapters()
    async with SessionLocal() as session:
        await close_interrupted_runs(session)


async def close_interrupted_runs(session) -> int:
    """Mark runs a previous worker left RUNNING as failed: it was stopped mid-run.

    A run's row is closed by the run itself, so a worker stopped mid-run (a
    deploy, a pause, a crash) leaves it RUNNING forever, and `make status` then
    reports a sweep as active for days when nothing is running. Nothing is
    running when a worker starts, so every RUNNING row is one of those. The
    work it did is kept: progress is durable per page, and the next run resumes
    from the cursor.
    """
    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(IngestionRun)
        .where(IngestionRun.status == IngestionStatus.RUNNING)
        .values(
            status=IngestionStatus.FAILED,
            finished_at=now,
            error="interrupted: the worker stopped during this run; the next run resumes it",
        )
    )
    await session.commit()
    return result.rowcount or 0


def _summarize(source_id: str, run) -> dict:
    return {
        "source": source_id,
        "status": run.status,
        "seen": run.items_seen,
        "created": run.items_created,
        "updated": run.items_updated,
        "for_review": run.items_for_review,
        "failed": run.items_failed,
        "archived": run.stats.get("archived", 0),
    }


async def run_source(ctx: dict, source_id: str, limit: int | None = None) -> dict:
    """Arq task: run one source adapter end-to-end (enqueue manually)."""
    run = await _run_source(source_id, get(source_id), limit=limit)
    return _summarize(source_id, run)


async def run_partition(
    ctx: dict, source_id: str, partition: str, limit: int | None = None
) -> dict:
    """Arq task: run ONE partition of a source.

    The finer-grained unit of work. Partitions of a source share a host, so a
    single worker sweeps them sequentially to respect polite_delay; enqueueing
    them separately only pays off across workers with distinct egress IPs.
    """
    run = await _run_partition(source_id, get(source_id), partition, limit=limit)
    return _summarize(f"{source_id}[{partition}]", run)


async def refresh_all(ctx: dict) -> list[dict]:
    """Cron task: re-scrape every enabled source (full runs), regroup products, reindex.

    Sources are scraped concurrently (bounded by MAX_CONCURRENT_SOURCES) because
    each targets a different host with its own rate limit — wall-clock drops to
    roughly the slowest single source instead of the sum. One source failing
    outright doesn't abort the batch; it's recorded and the rest continue.
    """
    if not CRAWL_ENABLED:
        return [{"status": "skipped", "reason": "CRAWL_ENABLED is off"}]

    await load_adapters()
    adapters = all_enabled()
    sem = asyncio.Semaphore(MAX_CONCURRENT_SOURCES)

    async def _guarded(adapter):
        async with sem:
            return await _run_source(adapter.source_id, adapter)

    settled = await asyncio.gather(*(_guarded(a) for a in adapters), return_exceptions=True)
    results = []
    for adapter, outcome in zip(adapters, settled):
        if isinstance(outcome, Exception):
            results.append({"source": adapter.source_id, "status": "error", "error": str(outcome)})
        else:
            results.append(_summarize(adapter.source_id, outcome))

    async with SessionLocal() as session:
        await rebuild_products(session)
        # Reindex so search reflects the fresh catalog — without this the daily
        # scrape updates the DB but the search index goes stale.
        await reindex_all(session, get_client())
        # Redirects nobody has followed in a year (docs/decisions/
        # 0005-url-retirement.md). Cheap, and a no-op until one is that old.
        await retire_unused_redirects(session)
    return results


class WorkerSettings:
    functions = [run_source, run_partition]
    cron_jobs = [cron(refresh_all, hour=REFRESH_HOUR, minute=0, timeout=JOB_TIMEOUT)]
    # Also for run_source / run_partition jobs enqueued by hand.
    job_timeout = JOB_TIMEOUT
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379"))
