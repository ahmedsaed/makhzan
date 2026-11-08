"""Every product page, for the web app's sitemap.

Search cannot enumerate products: it pages 100 hits at a time and stops at
50,000. This walks the products table by id instead (keyset paging), selecting
only what a sitemap entry needs: the id and title for the URL, and when the
product's visible content last changed for `lastmod`.

At `/sitemap/products` rather than `/products/sitemap`, where it would sit
beside `/products/{product_id}` and work only for as long as it stayed declared
first: FastAPI matches routes in order, and "sitemap" is not a UUID, so the
wrong order answers 422.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.deps import get_session
from fastapi import APIRouter, Depends, Query
from makhzan_schemas.enums import ListingStatus
from makhzan_schemas.models import Listing, Product
from pydantic import BaseModel
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["sitemap"])

#: The most URLs one sitemap file may hold (sitemaps.org, and Google).
SITEMAP_MAX = 50_000


class SitemapProduct(BaseModel):
    id: uuid.UUID
    title_en: str | None
    changed_at: datetime


class SitemapPage(BaseModel):
    items: list[SitemapProduct]
    #: Pass as `after` for the next page; null on the last.
    next: uuid.UUID | None
    #: How many products there are in all. On the first page only (no `after`),
    #: which is the one a caller sizes its sitemap index from.
    total: int | None = None


# A product page 404s when it has no offers (apps/web, products/[id]/page.tsx).
# Rebuilds delete products whose offers are all gone, but a listing archived
# since the last rebuild still points at its product: ask for an active offer,
# so the sitemap never lists a page that is about to disappear.
_has_active_offer = exists().where(
    Listing.product_id == Product.id, Listing.status == ListingStatus.ACTIVE
)


@router.get("/sitemap/products", response_model=SitemapPage)
async def sitemap_products(
    after: uuid.UUID | None = None,
    limit: int = Query(SITEMAP_MAX, ge=1, le=SITEMAP_MAX),
    session: AsyncSession = Depends(get_session),
) -> SitemapPage:
    """Products with an active offer, ordered by id, `limit` after `after`."""
    query = (
        select(Product.id, Product.title_en, Product.content_changed_at)
        .where(_has_active_offer)
        .order_by(Product.id)
        .limit(limit)
    )
    if after is not None:
        query = query.where(Product.id > after)
    rows = (await session.execute(query)).all()

    total = None
    if after is None:
        total = await session.scalar(
            select(func.count()).select_from(Product).where(_has_active_offer)
        )

    return SitemapPage(
        items=[
            SitemapProduct(id=r.id, title_en=r.title_en, changed_at=r.content_changed_at)
            for r in rows
        ],
        # A full page may be followed by more; a short one is the last.
        next=rows[-1].id if len(rows) == limit else None,
        total=total,
    )
