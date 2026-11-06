"""Backfill category_id for existing listings and rebuild the search index.

Re-runnable maintenance task: seeds the taxonomy, assigns each listing a category
via the resolver, then reindexes so category facets/filters appear in search.

Run:  poetry run python -m worker.backfill
"""

from __future__ import annotations

import asyncio

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.grouping import rebuild_products
from makhzan_schemas.models import Listing
from makhzan_schemas.domains import get_profile
from sqlalchemy import select

from worker.categorize import category_slug_for, seed_categories
from worker.indexer import get_client, reindex_all


async def main() -> None:
    async with SessionLocal() as session:
        cat_index = await seed_categories(session)
        listings = (await session.execute(select(Listing))).scalars().all()

        assigned = 0
        with_pn = 0
        for listing in listings:
            slug = category_slug_for(listing.attributes, listing.title_en or listing.title_ar)
            cat = cat_index.get(slug) if slug else None
            listing.category_id = cat.id if cat else None
            if cat:
                assigned += 1

            profile = get_profile(listing.domain)
            listing.part_number = profile.extract_identifier(listing.title_en or listing.title_ar)
            if listing.part_number:
                with_pn += 1

        await session.commit()
        n = len(listings)
        print(
            f"categorized {assigned}/{n} ({100 * assigned / max(n, 1):.1f}%) · "
            f"part numbers {with_pn}/{n} ({100 * with_pn / max(n, 1):.1f}%)"
        )

        # Group listings into canonical products (needs part numbers set above).
        result = await rebuild_products(session)
        print(
            f"products: {result['products']} "
            f"({result['multi_supplier']} multi-supplier, removed {result['removed']})"
        )

        count = await reindex_all(session, get_client())
        print(f"reindexed {count} documents")


if __name__ == "__main__":
    asyncio.run(main())
