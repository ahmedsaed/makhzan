"""Initial data load / full manual refresh (no Redis needed).

Runs every enabled source once, regroups products, and rebuilds the search
index — the same work as the daily `refresh_all` cron, but invokable directly so
a fresh deploy has data immediately instead of waiting for the first cron tick.

Run (inside the ingestion container):  python -m worker.seed
"""

from __future__ import annotations

import asyncio

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.grouping import rebuild_products

from worker.indexer import get_client, reindex_all
from worker.pipeline import run_source
from worker.sources.registry import all_enabled, load_adapters


async def main() -> None:
    await load_adapters()
    for adapter in all_enabled():
        run = await run_source(adapter.source_id, adapter)
        print(
            f"{adapter.source_id:22} status={run.status} seen={run.items_seen} "
            f"created={run.items_created} updated={run.items_updated} "
            f"review={run.items_for_review} failed={run.items_failed}",
            flush=True,
        )
    async with SessionLocal() as session:
        result = await rebuild_products(session)
        print(
            f"products: {result['products']} "
            f"({result['multi_supplier']} multi-supplier, removed {result['removed']})",
            flush=True,
        )
        count = await reindex_all(session, get_client())
        print(f"reindexed {count} documents", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
