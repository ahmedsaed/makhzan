"""Regroup listings into products, then rebuild the search index. Nothing else.

The safe command after a grouping change, or when the index has drifted: it
reads listings as they are (categories, part numbers, prices untouched),
recomputes which listings form one product, and reloads Meilisearch from the
result. Re-runnable; the index is a disposable projection of the database.

Product ids are permanent (docs/decisions/0004-stable-product-ids.md): a
grouping change merges or splits products, each recorded in `product_events`,
and every existing id keeps working, as a product or as a redirect to one.
`--dry-run` reports what a regroup would do and changes nothing, the search
index included.

Not to be confused with `worker.backfill`, which re-infers every category from
titles first and so erases the categories crosswalks set.

Run (inside the ingestion container):  python -m worker.regroup [--dry-run]
"""

from __future__ import annotations

import asyncio
import sys

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.grouping import describe, rebuild_products

from worker.indexer import get_client, reindex_all


async def main(dry_run: bool = False) -> None:
    async with SessionLocal() as session:
        grouped = await rebuild_products(session, dry_run=dry_run)
        print(("would regroup: " if dry_run else "") + describe(grouped), flush=True)
        if dry_run:
            return
        count = await reindex_all(session, get_client())
        print(f"reindexed {count} documents", flush=True)


if __name__ == "__main__":
    asyncio.run(main(dry_run="--dry-run" in sys.argv[1:]))
