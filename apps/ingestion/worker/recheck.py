"""Re-check first: a listing a person asked to be read again before its turn.

Accepting a "wrong price or stock" report (admin dashboard, or `./makhzan
reports accept`) sets `listings.recheck_requested_at` on the offers the visitor
ticked (owner decision, 2026-11-17). The next full run of that listing's source
reads it first, within the run's pace, robots.txt and page ceiling, where its
adapter can (`how`):

- `by_id`: an adapter that can re-read listings by id (`rechecks_by_id`, the
  WooCommerce Store API's `include`, which the archive confirmation already
  uses) re-reads them at the start of the run, before the sweep
  (`pipeline._recheck_first`), counted as `stats.requests.recheck` and
  reported as `stats.recheck`;
- `partition`: otherwise it waits for its partition's turn in the cycle. A
  shop's details stage does not count (owner decision, 2026-11-17): a
  product page read (`fetch_details`) never writes price or stock, so it
  could not answer a price or stock report, and it neither puts a marked
  listing first nor clears its marker.

Only a read that writes price and stock clears the marker: a sweep's or a
re-read's upsert (`pipeline._upsert_listing`). A
re-read that finds the listing gone from the shop clears it too: it was asked,
and the cycle's own archiving decides the rest (`stats.recheck.absent`). Not on
a shop whose Store API hides out-of-stock products (`hides_out_of_stock`):
`include` omits those too, so "not returned" may mean "out of stock", the very
report, and the marker stays (`stats.recheck.hidden_kept`) for the unlisted
pass, which reads the stock by id (`pipeline._mark_out_of_stock` clears it),
or the sweep. A `limit=` run never reads a
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

BY_ID, PARTITION = "by_id", "partition"


def how(adapter: SourceAdapter) -> str:
    """How `adapter`'s next run honours a re-check: by id first, or at its partition's turn."""
    if (
        getattr(adapter, "rechecks_by_id", False)
        and type(adapter).confirm_listed is not SourceAdapter.confirm_listed
    ):
        return BY_ID
    return PARTITION


WORDS = {
    BY_ID: "re-read by id at the start of its next run",
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
