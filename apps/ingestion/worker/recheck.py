"""Re-check first: a listing a person asked to be read again before its turn.

Accepting a "wrong price or stock" report (admin dashboard, or `./makhzan
reports accept`) sets `listings.recheck_requested_at` on the offers the visitor
ticked (owner decision, 2026-11-17). The next full run of that listing's source
reads it first, within the run's pace, robots.txt and page ceiling, in the one
way its adapter can (`how`):

- `by_id`: an adapter that can re-read listings by id (`rechecks_by_id`, the
  WooCommerce Store API's `include`, which the archive confirmation already
  uses) re-reads them at the start of the run, before the sweep
  (`pipeline._recheck_first`), counted as `stats.requests.recheck` and
  reported as `stats.recheck`;
- `details`: an adapter with its details stage on reads their product pages
  first in that stage (`details.due_listings`, reason "recheck"). When that
  run's sweep reaches the listing's card first, the card's price and stock
  answer the report and clear the marker before the stage runs;
- `partition`: otherwise it waits for its partition's turn in the cycle.

Any full read of the listing clears the marker: a sweep's or a re-read's
upsert (`pipeline._upsert_listing`), or its product page read (details). A
re-read that finds the listing gone from the shop clears it too: it was asked,
and the cycle's own archiving decides the rest. A `limit=` run never reads a
marked listing first, and a paused shop is not asked.
"""

from __future__ import annotations

from datetime import datetime, timezone

from makhzan_schemas.models import Listing
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from worker.sources.base import SourceAdapter

#: The `stats.requests` key, and the price observations' `via`.
LABEL = "recheck"
#: The most marked listings one run re-reads first (a WooCommerce request holds 100).
MAX_PER_RUN = 100

BY_ID, DETAILS, PARTITION = "by_id", "details", "partition"


def how(adapter: SourceAdapter) -> str:
    """How `adapter`'s next run honours a re-check: by id, through details, or not early."""
    if (
        getattr(adapter, "rechecks_by_id", False)
        and type(adapter).confirm_listed is not SourceAdapter.confirm_listed
    ):
        return BY_ID
    reads_pages = type(adapter).fetch_details is not SourceAdapter.fetch_details
    if reads_pages and adapter.details is not None and adapter.details.enabled:
        return DETAILS
    return PARTITION


WORDS = {
    BY_ID: "re-read by id at the start of its next run",
    DETAILS: "its product page read first by the next run's details stage",
    PARTITION: "no early read for this shop: it waits for its partition in the cycle",
}


async def request(session: AsyncSession, listing_ids) -> int:
    """Mark listings for a re-check (flushed, not committed). Returns how many were marked.

    A listing already marked keeps its first request's time, so it keeps its
    place in the queue.
    """
    ids = list(listing_ids)
    if not ids:
        return 0
    await session.execute(
        update(Listing)
        .where(Listing.id.in_(ids), Listing.recheck_requested_at.is_(None))
        .values(recheck_requested_at=datetime.now(timezone.utc))
        .execution_options(synchronize_session=False)
    )
    await session.flush()
    marked = await session.scalar(
        select(func.count())
        .select_from(Listing)
        .where(Listing.id.in_(ids), Listing.recheck_requested_at.is_not(None))
    )
    return int(marked or 0)


async def due(session: AsyncSession, source_id: str, limit: int = MAX_PER_RUN) -> list[Listing]:
    """The source's marked listings, oldest request first."""
    return list(
        await session.scalars(
            select(Listing)
            .where(Listing.source == source_id, Listing.recheck_requested_at.is_not(None))
            .order_by(Listing.recheck_requested_at, Listing.id)
            .limit(limit)
        )
    )


async def clear(session: AsyncSession, listing_ids) -> None:
    """Clear the marker on listings that were asked about (flushed, not committed)."""
    ids = list(listing_ids)
    if ids:
        await session.execute(
            update(Listing)
            .where(Listing.id.in_(ids))
            .values(recheck_requested_at=None)
            .execution_options(synchronize_session=False)
        )
        await session.flush()


async def pending(session: AsyncSession) -> list[dict]:
    """Every source with listings waiting for a re-check: count and oldest request."""
    rows = (
        await session.execute(
            select(Listing.source, func.count(), func.min(Listing.recheck_requested_at))
            .where(Listing.recheck_requested_at.is_not(None))
            .group_by(Listing.source)
            .order_by(Listing.source)
        )
    ).all()
    return [{"source": source, "count": n, "oldest": oldest} for source, n, oldest in rows]
