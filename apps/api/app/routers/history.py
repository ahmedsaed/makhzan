"""Price and stock history: the change points the ingestion pipeline records.

Read-only and bounded: a window of at most a year, and at most `MAX_POINTS` per
offer. Rows are written only when a price or stock signal changes, so a normal
offer has a handful of points a quarter and the cap exists for the pathological
one. Both queries ride the (listing_id, observed_at) index.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app.deps import get_session
from fastapi import APIRouter, Depends, HTTPException, Query
from makhzan_schemas.contracts import ListingHistory, PricePoint, ProductHistory
from makhzan_schemas.models import Listing, PriceObservation, Product
from sqlalchemy import func, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["history"])

#: Longest window a caller may ask for, in days.
MAX_DAYS = 365
#: Most change points returned per offer; the newest are kept.
MAX_POINTS = 200

_DAYS = Query(90, ge=1, le=MAX_DAYS, description="How far back to look, in days")


async def _histories(
    session: AsyncSession, listing_ids: list[uuid.UUID], since: datetime
) -> dict[uuid.UUID, ListingHistory]:
    """Each listing's points since `since`, plus the one in force when it opened."""
    histories = {lid: ListingHistory(listing_id=lid, since=since, points=[]) for lid in listing_ids}
    if not listing_ids:
        return histories

    po = PriceObservation
    columns = (po.listing_id, po.observed_at, po.price, po.currency, po.stock_signal, po.in_stock)
    in_window = select(*columns).where(po.listing_id.in_(listing_ids), po.observed_at >= since)
    carried_in = (
        select(*columns)
        .where(po.listing_id.in_(listing_ids), po.observed_at < since)
        .order_by(po.listing_id, po.observed_at.desc())
        .distinct(po.listing_id)
        .subquery()
    )
    both = union_all(in_window, select(carried_in)).subquery()
    newest_first = (
        func.row_number()
        .over(partition_by=both.c.listing_id, order_by=both.c.observed_at.desc())
        .label("rank")
    )
    ranked = select(both, newest_first).subquery()
    rows = await session.execute(
        # One past the cap, so a truncated history can say so.
        select(ranked)
        .where(ranked.c.rank <= MAX_POINTS + 1)
        .order_by(ranked.c.listing_id, ranked.c.observed_at)
    )

    points: dict[uuid.UUID, list[PricePoint]] = defaultdict(list)
    for row in rows:
        points[row.listing_id].append(PricePoint.model_validate(row, from_attributes=True))
    for lid, found in points.items():
        history = histories[lid]
        history.truncated = len(found) > MAX_POINTS
        history.points = found[-MAX_POINTS:]
    return histories


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


@router.get("/listings/{listing_id}/history", response_model=ListingHistory)
async def listing_history(
    listing_id: uuid.UUID,
    days: int = _DAYS,
    session: AsyncSession = Depends(get_session),
) -> ListingHistory:
    if await session.get(Listing, listing_id) is None:
        raise HTTPException(status_code=404, detail="listing not found")
    return (await _histories(session, [listing_id], _since(days)))[listing_id]


@router.get("/products/{product_id}/history", response_model=ProductHistory)
async def product_history(
    product_id: uuid.UUID,
    days: int = _DAYS,
    session: AsyncSession = Depends(get_session),
) -> ProductHistory:
    """The history of every offer of a product: the same offers its page lists."""
    if await session.get(Product, product_id) is None:
        raise HTTPException(status_code=404, detail="product not found")
    listing_ids = list(
        (await session.execute(select(Listing.id).where(Listing.product_id == product_id)))
        .scalars()
        .all()
    )
    since = _since(days)
    histories = await _histories(session, listing_ids, since)
    return ProductHistory(product_id=product_id, since=since, offers=list(histories.values()))
