"""Remove a source and everything it put in the database.

    python -m worker.sources.retire SOURCE_ID          # show what would go
    python -m worker.sources.retire SOURCE_ID --yes    # delete it, regroup, reindex

For a source that should never have been in a database — a test source that
reached production — or a supplier makhzan no longer lists. Disabling a source
(`enabled = false`) only stops it being crawled; its listings stay on the site.

Deletes the source's listings, runs, cursors and review items, its row in
`sources`, its supplier unless another source still lists under it, and the
products only it ever offered. Then products are regrouped (a product another
source also offered keeps its id) and the search index is rebuilt to match. The
deletes are one transaction.

Remove the source from sources.toml first. Otherwise the next sync puts the
row back. It brings back no listings, though, only the row.
"""

from __future__ import annotations

import asyncio
import sys

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import IngestionStatus
from makhzan_schemas.grouping import rebuild_products
from makhzan_schemas.models import (
    IngestionRun,
    Listing,
    Product,
    ReviewQueueItem,
    Source,
    SourceCursor,
    Supplier,
)
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from worker.indexer import get_client, reindex_all


async def _orphaned_suppliers(session: AsyncSession, source_id: str) -> list[Supplier]:
    """Suppliers this source lists under that no other source does."""
    mine = select(Listing.supplier_id).where(Listing.source == source_id).distinct()
    shared = (
        select(Listing.supplier_id)
        .where(Listing.source != source_id, Listing.supplier_id.in_(mine))
        .distinct()
    )
    query = select(Supplier).where(Supplier.id.in_(mine), Supplier.id.not_in(shared))
    return list((await session.execute(query)).scalars())


async def plan(session: AsyncSession, source_id: str) -> dict[str, int | list[str]]:
    """What retiring `source_id` would delete, without deleting it."""

    async def count(model) -> int:
        query = select(func.count()).select_from(model).where(model.source == source_id)
        return (await session.execute(query)).scalar_one()

    return {
        "listings": await count(Listing),
        "ingestion_runs": await count(IngestionRun),
        "source_cursors": await count(SourceCursor),
        "review_queue": await count(ReviewQueueItem),
        "sources": (
            await session.execute(
                select(func.count()).select_from(Source).where(Source.source_id == source_id)
            )
        ).scalar_one(),
        "suppliers": [s.slug for s in await _orphaned_suppliers(session, source_id)],
    }


class SourceRunning(RuntimeError):
    """A run of the source is in progress; retiring under it would race it."""


async def retire(session: AsyncSession, source_id: str) -> None:
    """Delete everything `plan` reports, in one transaction.

    Refuses while a run of the source is in progress. This runs in its own
    process, which the worker's per-source lock cannot see, and a run going
    on would write listings back as they are deleted. (A run the worker left
    behind is closed when it starts, so a RUNNING row is a live one.) Once the
    `sources` row is gone, a daily job queued earlier skips the source.
    """
    running = await session.scalar(
        select(func.count())
        .select_from(IngestionRun)
        .where(IngestionRun.source == source_id, IngestionRun.status == IngestionStatus.RUNNING)
    )
    if running:
        raise SourceRunning(
            f"a run of {source_id!r} is in progress; wait for it, or "
            "`./makhzan crawl off`, then retry"
        )
    suppliers = [s.id for s in await _orphaned_suppliers(session, source_id)]
    # Products only this source ever offered go with it. A regroup never deletes
    # a product (its id is permanent, and a withdrawn one says "no longer
    # listed"), but a source being retired should never have been listed at
    # all. Ones merged into them go too: they only redirect there.
    theirs = select(Listing.product_id).where(
        Listing.source == source_id, Listing.product_id.is_not(None)
    )
    others = select(Listing.product_id).where(
        Listing.source != source_id, Listing.product_id.is_not(None)
    )
    doomed = list(
        (await session.execute(select(Product.id).where(Product.id.in_(theirs.except_(others)))))
        .scalars()
        .all()
    )
    if doomed:
        await session.execute(delete(Product).where(Product.merged_into.in_(doomed)))
        await session.execute(delete(Product).where(Product.id.in_(doomed)))
    # Review items point at listings and runs with SET NULL, so they go first
    # rather than lingering as rows about a source that no longer exists.
    for model in (ReviewQueueItem, Listing, IngestionRun, SourceCursor):
        await session.execute(delete(model).where(model.source == source_id))
    await session.execute(delete(Source).where(Source.source_id == source_id))
    if suppliers:
        await session.execute(delete(Supplier).where(Supplier.id.in_(suppliers)))
    await session.commit()


async def main(source_id: str, confirmed: bool) -> None:
    async with SessionLocal() as session:
        found = await plan(session, source_id)
        print(f"retiring {source_id!r} removes:")
        for what, n in found.items():
            print(f"  {what:15} {', '.join(n) or '-' if isinstance(n, list) else n}")
        if not any(found.values()):
            print("nothing to remove.")
            return
        if not confirmed:
            print("\ndry run; add --yes to delete.")
            return
        try:
            await retire(session, source_id)
        except SourceRunning as refused:
            raise SystemExit(str(refused)) from None
        print("deleted. rebuilding products and the search index...")
        print("  products:", await rebuild_products(session))
        print("  indexed:", await reindex_all(session, get_client()))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--yes"]
    if len(args) != 1:
        raise SystemExit(__doc__)
    asyncio.run(main(args[0], "--yes" in sys.argv[1:]))
