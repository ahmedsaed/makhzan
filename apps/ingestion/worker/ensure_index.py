"""Apply the search index's settings: `python -m worker.ensure_index`.

Run by the `migrate` service on every deploy, before the API starts, and by
`make migrate` locally, so the index always knows the attributes the new code
searches, filters and sorts on. Without this, a release that makes an attribute
filterable (the stale filter's `last_verified_at`) or searchable (the member
arrays) breaks search from the deploy until the next reindex: Meilisearch
rejects a query naming an attribute its settings do not list.

Settings only: documents are untouched, so this is safe to repeat. Meilisearch
may still be starting when `migrate` runs, so it waits for it.

When `searchableAttributes` changed, the documents already indexed lack what
the new attributes search: search works but finds nothing through them. So
this also queues the worker's `rebuild_and_reindex` under the rebuild window's
job id, shared with any rebuild already due, and the new worker fills them
within the window. If Redis cannot be reached it says so and asks for
`make reindex`; the deploy itself does not fail over that.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from datetime import datetime, timezone

import meilisearch
from makhzan_schemas import rebuild as _rebuild

from worker.indexer import TASK_TIMEOUT_MS, ensure_index, get_client

ATTEMPTS = 30
WAIT_SECONDS = 2.0


async def enqueue_rebuild() -> str | None:
    """Queue `rebuild_and_reindex` for this window; its job id, or None when a
    rebuild with that id is already queued. Replaced in tests."""
    from arq import create_pool
    from arq.connections import RedisSettings

    job_id, runs_at = _rebuild.rebuild_job_id(datetime.now(timezone.utc))
    redis = await create_pool(
        RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379"))
    )
    try:
        job = await redis.enqueue_job(
            _rebuild.REBUILD_FUNCTION, _job_id=job_id, _defer_until=runs_at
        )
    finally:
        await redis.aclose()
    return job_id if job is not None else None


def queue_reindex() -> None:
    try:
        job_id = asyncio.run(enqueue_rebuild())
    except Exception as exc:  # noqa: BLE001 — search works; only the fill waits
        print(
            "NOTE: the search index's searchable attributes changed, and queueing a "
            f"rebuild failed ({exc}). Search works, but finds nothing through the new "
            "attributes until the next rebuild: run `make reindex` (in production, "
            "`python -m worker.regroup` in the ingestion container) to fill them now.",
            file=sys.stderr,
        )
        return
    if job_id:
        print(f"searchable attributes changed: queued {job_id} to reindex the documents")
    else:
        print("searchable attributes changed: a rebuild is already queued for this window")


def main() -> int:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            changed = ensure_index(get_client())
        except (meilisearch.errors.MeilisearchCommunicationError, OSError) as exc:
            if attempt == ATTEMPTS:
                print(f"search index settings not applied: {exc}", file=sys.stderr)
                return 1
            time.sleep(WAIT_SECONDS)
            continue
        except meilisearch.errors.MeilisearchTimeoutError as exc:
            # Fail the deploy: the new API's queries name the new attributes and
            # would be rejected until the settings land, while the running API
            # keeps working. Meilisearch finishes the task on its own.
            print(
                f"search index settings not applied within {TASK_TIMEOUT_MS // 1000} s "
                f"({exc}). Meilisearch keeps applying them; deploy again once its "
                "settings task has succeeded (GET /tasks?statuses=processing,enqueued "
                "is empty).",
                file=sys.stderr,
            )
            return 1
        print("search index settings applied")
        if changed:
            queue_reindex()
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
