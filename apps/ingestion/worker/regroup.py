"""Regroup listings into products, then rebuild the search index. Nothing else.

The safe command after a grouping change, or when the index has drifted: it
reads listings as they are (categories and prices untouched), re-reads each
one's identifier with the current rules and family guard
(`grouping.assign_identifiers`), recomputes which listings form one product,
and reloads Meilisearch from the result. Re-runnable; the index is a disposable projection of the database.

Product ids are permanent (docs/decisions/0004-stable-product-ids.md): a
grouping change merges or splits products, each recorded in `product_events`,
and every existing id keeps working, as a product or as a redirect to one.
`--dry-run` reports what a regroup would do and changes nothing, the search
index included.

Not to be confused with `worker.backfill`, which re-infers every category from
titles first and so erases the categories crosswalks set.

AI decisions are read only when the AI matching mode is `live`
(`makhzan_schemas.ai.mode`). `--dry-run --ai` previews what going live would
do: it reads standing "same" decisions, shadow ones included, whatever the
mode (`make regroup-dry-run ARGS=--ai`).

Run (inside the ingestion container):  python -m worker.regroup [--dry-run [--ai]]
"""

from __future__ import annotations

import asyncio
import sys

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.grouping import describe, rebuild_products

from worker.indexer import get_client, reindex_all


async def main(dry_run: bool = False, ai_preview: bool = False) -> None:
    if ai_preview and not dry_run:
        raise SystemExit("--ai previews shadow decisions: use it with --dry-run")
    async with SessionLocal() as session:
        grouped = await rebuild_products(
            session, dry_run=dry_run, reidentify=True, ai_preview=ai_preview
        )
        print(("would regroup: " if dry_run else "") + describe(grouped), flush=True)
        if dry_run:
            return
        count = await reindex_all(session, get_client())
        print(f"reindexed {count} documents", flush=True)


if __name__ == "__main__":
    asyncio.run(main(dry_run="--dry-run" in sys.argv[1:], ai_preview="--ai" in sys.argv[1:]))
