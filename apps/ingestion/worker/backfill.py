"""DESTRUCTIVE: re-infer every listing's category from its title, then regroup.

!!! Not for regrouping or reindexing: that is `python -m worker.regroup`. !!!

This overwrites `category_id` on every listing with a keyword guess from the
title, which erases every category a crosswalk set: a source browsed by
category loses all of them, and a tag-cloud shop's mapped tags give way to
inference. Only a re-crawl of each source puts them back. Identifiers are re-read
by the regroup that follows, as every regroup does. It dates from before
crosswalks, when inference was all there was.

Run:  python -m worker.backfill --i-understand-this-erases-crosswalk-categories
"""

from __future__ import annotations

import asyncio
import sys

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.grouping import describe, rebuild_products
from makhzan_schemas.models import Listing
from sqlalchemy import select

from worker.categorize import category_slug_for, seed_categories
from worker.indexer import get_client, reindex_all


async def main() -> None:
    async with SessionLocal() as session:
        cat_index = await seed_categories(session)
        listings = (await session.execute(select(Listing))).scalars().all()

        assigned = 0
        for listing in listings:
            slug = category_slug_for(listing.attributes, listing.title_en or listing.title_ar)
            cat = cat_index.get(slug) if slug else None
            listing.category_id = cat.id if cat else None
            if cat:
                assigned += 1

        await session.commit()
        n = len(listings)
        print(f"categorized {assigned}/{n} ({100 * assigned / max(n, 1):.1f}%)")

        # Group listings into canonical products. The regroup re-reads every
        # identifier itself: it is the only writer of `part_number`.
        print(describe(await rebuild_products(session, reidentify=True)))

        count = await reindex_all(session, get_client())
        print(f"reindexed {count} documents")


CONFIRM = "--i-understand-this-erases-crosswalk-categories"

if __name__ == "__main__":
    if CONFIRM not in sys.argv[1:]:
        sys.exit(
            "worker.backfill re-infers EVERY listing's category from its title and erases\n"
            "the categories crosswalks set; only re-crawling each source restores them.\n"
            "To regroup products and rebuild the search index: python -m worker.regroup\n"
            f"To run backfill anyway, pass {CONFIRM}"
        )
    asyncio.run(main())
