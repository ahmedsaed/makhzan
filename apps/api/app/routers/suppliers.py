"""Suppliers endpoints — profile + the supplier's own listings (from the DB)."""

from __future__ import annotations

from app.deps import get_session
from fastapi import APIRouter, Depends, HTTPException, Query
from makhzan_schemas.contracts import ListingRead
from makhzan_schemas.enums import ListingStatus
from makhzan_schemas.models import Listing, Supplier
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

router = APIRouter(tags=["suppliers"])


async def _get_supplier(session: AsyncSession, slug: str) -> Supplier:
    supplier = (
        await session.execute(select(Supplier).where(Supplier.slug == slug))
    ).scalar_one_or_none()
    if supplier is None:
        raise HTTPException(status_code=404, detail="supplier not found")
    return supplier


@router.get("/suppliers/{slug}")
async def get_supplier(slug: str, session: AsyncSession = Depends(get_session)) -> dict:
    supplier = await _get_supplier(session, slug)
    count = await session.scalar(
        select(func.count())
        .select_from(Listing)
        .where(Listing.supplier_id == supplier.id, Listing.status == ListingStatus.ACTIVE)
    )
    return {
        "slug": supplier.slug,
        "name": supplier.name,
        "name_ar": supplier.name_ar,
        "area": supplier.area,
        "governorate": supplier.governorate,
        "website_url": supplier.website_url,
        "listing_count": count,
    }


@router.get("/suppliers/{slug}/listings")
async def supplier_listings(
    slug: str,
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict:
    supplier = await _get_supplier(session, slug)
    base = select(Listing).where(
        Listing.supplier_id == supplier.id, Listing.status == ListingStatus.ACTIVE
    )
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = (
        (
            await session.execute(
                base.options(selectinload(Listing.supplier), selectinload(Listing.category))
                .order_by(Listing.last_verified_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [ListingRead.model_validate(row) for row in rows],
    }
