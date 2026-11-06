"""Rebuild canonical products from listings, then reload the search index.

The Meilisearch index is a disposable projection of the database, so this is
always safe to re-run: it recomputes groupings first, then reindexes from the
result. Used after a bulk ingest or when the index drifts.
"""

from __future__ import annotations

import asyncio

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.grouping import rebuild_products
from worker.indexer import get_client, reindex_all


async def main() -> None:
    async with SessionLocal() as session:
        grouped = await rebuild_products(session)
        print("grouped:", grouped)
        print("indexed:", await reindex_all(session, get_client()))


if __name__ == "__main__":
    asyncio.run(main())
