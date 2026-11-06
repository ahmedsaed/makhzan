"""Regroup listings into products, then rebuild the search index. Nothing else.

The safe command after a grouping change, or when the index has drifted: it
reads listings as they are (categories, part numbers, prices untouched),
recomputes which listings form one product, and reloads Meilisearch from the
result. Re-runnable; the index is a disposable projection of the database.

Product ids follow group keys (docs/decisions/0004-stable-product-ids.md), so a
grouping change gives new ids to the products it splits or merges.

Not to be confused with `worker.backfill`, which re-infers every category from
titles first and so erases the categories crosswalks set.

Run (inside the ingestion container):  python -m worker.regroup
"""

from __future__ import annotations

import asyncio

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.grouping import rebuild_products

from worker.indexer import get_client, reindex_all


async def main() -> None:
    async with SessionLocal() as session:
        grouped = await rebuild_products(session)
        print(
            f"products: {grouped['products']} "
            f"({grouped['multi_supplier']} multi-supplier, removed {grouped['removed']})",
            flush=True,
        )
        count = await reindex_all(session, get_client())
        print(f"reindexed {count} documents", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
