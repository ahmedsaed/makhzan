"""Rebuild the Meilisearch index from the current database (no scraping).

Used after restoring a DB seed dump: the products/listings are already in
Postgres, so we only need to (re)build the search index from them.

Run (inside the ingestion container):  python -m worker.reindex
"""

from __future__ import annotations

import asyncio

from makhzan_schemas.db import SessionLocal

from worker.indexer import get_client, reindex_all


async def main() -> None:
    async with SessionLocal() as session:
        count = await reindex_all(session, get_client())
        print(f"reindexed {count} documents", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
