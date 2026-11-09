"""makhzan ingestion worker entrypoint (Arq).

Runs source adapters (scrapers / manual imports / portal syncs), normalizes
their output into Listings, and routes low-confidence items to a review queue.

Scheduling: a daily cron (`refresh_all`) enqueues one `crawl_source` job per
enabled source, each with its own timeout, so prices/stock stay fresh and
vanished products get archived. Every source job, however it ends, asks for a
product rebuild and reindex (`rebuild_and_reindex`), deduplicated so sources
finishing close together share one; the first rebuild of each day then retires
redirects unused for a year. Idempotent upserts mean re-runs update in
place. Run the worker:  arq worker.main.WorkerSettings
"""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from datetime import date, datetime, timedelta, timezone

from arq import cron
from arq.connections import RedisSettings
from arq.worker import func
from makhzan_schemas import crawl
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import IngestionStatus
from makhzan_schemas.grouping import rebuild_products
from makhzan_schemas.models import IngestionRun, Source, WorkerState
from sqlalchemy import func as sql_func
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from worker.indexer import get_client, reindex_all
from worker.pipeline import run_partition as _run_partition
from worker.pipeline import run_source as _run_source
from worker.retire_redirects import retire_unused_redirects
from worker.sources.registry import all_enabled, get, load_adapters

log = logging.getLogger(__name__)

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
#: It is the worker's `max_jobs`, less the one slot kept for the rebuild.
MAX_CONCURRENT_SOURCES = int(os.getenv("MAX_CONCURRENT_SOURCES", "8"))

#: How long one source's run may take before arq cancels it. arq's own default
#: is 300 s, which once killed the whole daily refresh mid-sweep every day. Per
#: source now, so a host stuck in a long Retry-After or a 429 loop is cut off
#: on its own, without holding the other sources or the rebuild. Pages are
#: durable, so a run cut off loses nothing; the next one resumes from its cursor.
JOB_TIMEOUT = int(os.getenv("REFRESH_TIMEOUT_SECONDS", str(6 * 3600)))

#: Sources finishing within one window of this many seconds share one rebuild,
#: run at the end of that window. Short next to a crawl, long next to a rebuild.
REBUILD_WINDOW = int(os.getenv("REBUILD_WINDOW_SECONDS", "600"))

#: How long the rebuild and reindex may take.
REBUILD_TIMEOUT = int(os.getenv("REBUILD_TIMEOUT_SECONDS", str(3600)))

#: One lock per source, held for the whole of any run of it (daily or by hand):
#: cursors, cycle bookkeeping and the pace gate all assume one run at a time.
#: In-process, which is where every job runs: the deployment has one worker.
_SOURCE_LOCKS: dict[str, asyncio.Lock] = {}

#: `worker_state` key holding the UTC day redirects were last retired, and the counts.
RETIRED_STATE_KEY = "redirects_retired"

#: Held while products are rebuilt, so two rebuilds never interleave.
_REBUILD_LOCK = asyncio.Lock()


async def startup(ctx: dict) -> None:
    await load_adapters()
    async with SessionLocal() as session:
        await close_interrupted_runs(session)
        # The API reports the crawl flag from here, not from its own
        # environment: `./makhzan crawl off` recreates this container alone.
        await crawl.record_crawl_enabled(session, CRAWL_ENABLED)


async def close_interrupted_runs(session) -> int:
    """Mark runs a previous worker left RUNNING as failed: it was stopped mid-run.

    A run's row is closed by the run itself, so a worker stopped mid-run (a
    deploy, a pause, a crash) leaves it RUNNING forever, and `make status` then
    reports a sweep as active for days when nothing is running. Called from
    `startup`, which arq finishes before it takes its first job, so nothing of
    this worker's is running yet and every RUNNING row is orphaned — however
    many jobs it then runs at once. That holds while there is one worker
    process; a second one starting would close the first one's live runs. The
    work an orphaned run did is kept: progress is durable per page, and the
    next run resumes from the cursor.
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


async def _exclusive(source_id: str, label: str, body: Callable[[], Awaitable]) -> dict:
    """Run `body` unless a run of this source is already in progress."""
    lock = _SOURCE_LOCKS.setdefault(source_id, asyncio.Lock())
    if lock.locked():
        return {"source": label, "status": "skipped", "reason": "a run of it is in progress"}
    async with lock:
        return _summarize(label, await body())


def crawl_job_id(source_id: str, day: date) -> str:
    """The daily job's id: arq enqueues one job per id, so one run per source a day."""
    return f"crawl:{source_id}:{day.isoformat()}"


def rebuild_job_id(now: datetime) -> tuple[str, datetime]:
    """The rebuild job for `now`'s window, and when it runs: the window's end."""
    window = int(now.timestamp()) // REBUILD_WINDOW
    runs_at = datetime.fromtimestamp((window + 1) * REBUILD_WINDOW, timezone.utc)
    return f"rebuild:{window}", runs_at


async def request_rebuild(ctx: dict) -> None:
    """Ask for a product rebuild and reindex at the end of this window.

    Deduplicated by the window's job id: every source finishing in it shares one
    rebuild, and one finishing later gets the next window's. Nothing is lost to
    the dedup — a window's rebuild runs after everything that asked for it.
    """
    job_id, runs_at = rebuild_job_id(datetime.now(timezone.utc))
    try:
        await ctx["redis"].enqueue_job("rebuild_and_reindex", _job_id=job_id, _defer_until=runs_at)
    except Exception:  # noqa: BLE001 — must not mask how the run itself ended
        log.exception("could not queue the rebuild; the next finishing run will")


async def source_enabled(source_id: str) -> bool:
    """Whether `sources` still has this source, enabled, as the job starts.

    The job was queued hours earlier from adapters loaded then. A source retired
    since (`worker.sources.retire`, run in another process, so `_SOURCE_LOCKS`
    cannot see it) must not be crawled back into the database.
    """
    async with SessionLocal() as session:
        enabled = await session.scalar(select(Source.enabled).where(Source.source_id == source_id))
    return bool(enabled)


async def crawl_source(ctx: dict, source_id: str) -> dict:
    """Arq task: one source's daily run, enqueued by `refresh_all`.

    Its own job, with its own timeout: one slow host no longer holds the others
    or the rebuild. However it ends — done, failed, or cancelled at the timeout
    — it asks for the rebuild, so search catches up with whatever it committed.
    """
    try:
        if not await source_enabled(source_id):
            return {"source": source_id, "status": "skipped", "reason": "retired or disabled"}
        return await _exclusive(
            source_id, source_id, lambda: _run_source(source_id, get(source_id))
        )
    finally:
        await request_rebuild(ctx)


async def run_source(ctx: dict, source_id: str, limit: int | None = None) -> dict:
    """Arq task: run one source adapter end-to-end (enqueue manually)."""
    summary = await _exclusive(
        source_id, source_id, lambda: _run_source(source_id, get(source_id), limit=limit)
    )
    if limit is None:
        await request_rebuild(ctx)
    return summary


async def run_partition(
    ctx: dict, source_id: str, partition: str, limit: int | None = None
) -> dict:
    """Arq task: run ONE partition of a source.

    The finer-grained unit of work. Partitions of a source share a host, so a
    single worker sweeps them sequentially to respect polite_delay; enqueueing
    them separately only pays off across workers with distinct egress IPs.
    """
    return await _exclusive(
        source_id,
        f"{source_id}[{partition}]",
        lambda: _run_partition(source_id, get(source_id), partition, limit=limit),
    )


async def retire_redirects_daily(session, today: date) -> dict | None:
    """Drop redirects unused for a year, unless that was already done `today`.

    Redirects nobody has followed in a year (docs/decisions/0005-url-retirement.md).
    Run after the regroup, under its lock: a regroup can revive a merged-away id
    that this would otherwise be deleting at the same moment. Once a day is
    plenty — the threshold is a year — and the day is kept in `worker_state`, so
    a restart does not repeat it. Returns the counts, or None when skipped.
    """
    state = await session.get(WorkerState, RETIRED_STATE_KEY)
    if state is not None and (state.value or {}).get("day") == today.isoformat():
        return None
    counts = await retire_unused_redirects(session)
    value = {"day": today.isoformat(), **counts}
    await session.execute(
        insert(WorkerState)
        .values(key=RETIRED_STATE_KEY, value=value)
        .on_conflict_do_update(
            index_elements=[WorkerState.key], set_={"value": value, "updated_at": sql_func.now()}
        )
    )
    await session.commit()
    return counts


async def rebuild_and_reindex(ctx: dict) -> str:
    """Arq task: regroup products and rebuild the search index from the database,
    then, once a day, retire redirects nobody uses any more.

    Without it the crawl updates the database but search goes stale.
    """
    async with _REBUILD_LOCK:
        async with SessionLocal() as session:
            await rebuild_products(session)
            await reindex_all(session, get_client())
            try:
                retired = await retire_redirects_daily(session, datetime.now(timezone.utc).date())
            except Exception:  # noqa: BLE001 — search is rebuilt; retirement retries tomorrow
                log.exception("retiring unused redirects failed")
                await session.rollback()
                return "rebuilt; retiring redirects failed"
    if retired is None:
        return "rebuilt"
    return (
        f"rebuilt; retired {retired['merged_products']} merged product ids and "
        f"{retired['product_redirects']} older redirects"
    )


async def refresh_all(ctx: dict) -> list[dict]:
    """Cron task: enqueue one `crawl_source` job per enabled source.

    It returns as soon as they are queued. Each job runs on its own, bounded by
    the worker's `max_jobs`, with its own timeout, and a failure in one is
    recorded on its own run; the rest carry on. The job id names the source and
    the day, so a source is never queued twice for one day, and `_exclusive`
    keeps a run started by hand from overlapping it.
    """
    if not CRAWL_ENABLED:
        return [{"status": "skipped", "reason": "CRAWL_ENABLED is off"}]

    await load_adapters()
    today = datetime.now(timezone.utc).date()
    queued = []
    for adapter in all_enabled():
        job = await ctx["redis"].enqueue_job(
            "crawl_source", adapter.source_id, _job_id=crawl_job_id(adapter.source_id, today)
        )
        queued.append(
            {"source": adapter.source_id, "status": "queued" if job else "already queued"}
        )
    return queued


class WorkerSettings:
    functions = [
        # Not retried: a run cut off (a deploy, the timeout) resumes from its
        # cursor at the next daily run, rather than at once at an unplanned hour.
        func(crawl_source, timeout=JOB_TIMEOUT, max_tries=1),
        func(rebuild_and_reindex, timeout=REBUILD_TIMEOUT, max_tries=1),
        run_source,
        run_partition,
    ]
    cron_jobs = [cron(refresh_all, hour=REFRESH_HOUR, minute=0, timeout=timedelta(minutes=5))]
    # Also for run_source / run_partition jobs enqueued by hand.
    job_timeout = JOB_TIMEOUT
    # Up to MAX_CONCURRENT_SOURCES sources at once, plus one slot so a rebuild
    # can run while they do. arq does not reserve the slot: with more enabled
    # sources than that, the extra ones and the rebuild queue for a free slot.
    max_jobs = MAX_CONCURRENT_SOURCES + 1
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379"))
