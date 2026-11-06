"""Suppliers endpoints — every shop, one shop's profile, and its listings (from the DB).

All of it is scoped to ACTIVE listings. That is the load-bearing part: a sweep
archives listings it no longer sees, and a page that kept counting them would
advertise stock the supplier has withdrawn.
"""

from __future__ import annotations

import uuid
from collections import defaultdict

from app.deps import get_session
from fastapi import APIRouter, Depends, HTTPException, Query
from makhzan_schemas.contracts import ListingRead
from makhzan_schemas.enums import ListingStatus, StockSignal
from makhzan_schemas.models import Category, Listing, Supplier
from makhzan_schemas.search import category_ref
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

router = APIRouter(tags=["suppliers"])

#: How many categories a shop page lists under "biggest categories".
TOP_CATEGORIES = 8

_ACTIVE = Listing.status == ListingStatus.ACTIVE
# IN_STOCK only, matching Product.in_stock: the two counts would otherwise
# disagree about the same listings on adjacent pages.
_IN_STOCK = Listing.stock_signal == StockSignal.IN_STOCK


async def _get_supplier(session: AsyncSession, slug: str) -> Supplier:
    supplier = (
        await session.execute(select(Supplier).where(Supplier.slug == slug))
    ).scalar_one_or_none()
    if supplier is None:
        raise HTTPException(status_code=404, detail="supplier not found")
    return supplier


async def _activity(session: AsyncSession, supplier_id: uuid.UUID | None = None) -> dict:
    """Per supplier: active listings, how many are in stock, and when it was last checked.

    `last_verified_at` is the latest of its active listings, which is the honest
    answer to "how fresh is this shop's data": a shop the crawler can no longer
    reach keeps its listings but stops advancing this.
    """
    query = (
        select(
            Listing.supplier_id,
            func.count(),
            func.count().filter(_IN_STOCK),
            func.max(Listing.last_verified_at),
        )
        .where(_ACTIVE)
        .group_by(Listing.supplier_id)
    )
    if supplier_id is not None:
        query = query.where(Listing.supplier_id == supplier_id)
    return {
        sid: {"listing_count": total, "in_stock_count": in_stock, "last_verified_at": latest}
        for sid, total, in_stock, latest in (await session.execute(query)).all()
    }


async def _domains(session: AsyncSession, supplier_id: uuid.UUID | None = None) -> dict:
    """Per supplier: its active listings by vertical, largest first.

    Keyed off the listing's own domain, not Supplier.domain: a shop can span
    verticals, and the supplier's domain is only a fallback for uncategorized
    listings.
    """
    query = (
        select(Listing.supplier_id, Listing.domain, func.count())
        .where(_ACTIVE)
        .group_by(Listing.supplier_id, Listing.domain)
        # Ties broken by name so the order is stable between requests.
        .order_by(Listing.supplier_id, func.count().desc(), Listing.domain)
    )
    if supplier_id is not None:
        query = query.where(Listing.supplier_id == supplier_id)
    out: dict = defaultdict(list)
    for sid, domain, n in (await session.execute(query)).all():
        out[sid].append({"domain": domain, "count": n})
    return out


def _summary(supplier: Supplier, activity: dict, domains: dict) -> dict:
    stats = activity.get(supplier.id, {})
    return {
        "listing_count": stats.get("listing_count", 0),
        "in_stock_count": stats.get("in_stock_count", 0),
        "last_verified_at": stats.get("last_verified_at"),
        "domains": domains.get(supplier.id, []),
    }


@router.get("/suppliers")
async def list_suppliers(session: AsyncSession = Depends(get_session)) -> list[dict]:
    """Every supplier, biggest first. Includes ones with no active listings, so a
    shop the crawler lost entirely still appears (with zeros) rather than vanishing;
    hiding it is the page's call."""
    suppliers = (await session.execute(select(Supplier))).scalars().all()
    activity = await _activity(session)
    domains = await _domains(session)
    rows = [
        {
            "slug": s.slug,
            "name": s.name,
            "name_ar": s.name_ar,
            "website_url": s.website_url,
            **_summary(s, activity, domains),
        }
        for s in suppliers
    ]
    rows.sort(key=lambda r: (-r["listing_count"], r["name"].casefold(), r["slug"]))
    return rows


@router.get("/suppliers/{slug}")
async def get_supplier(slug: str, session: AsyncSession = Depends(get_session)) -> dict:
    supplier = await _get_supplier(session, slug)
    activity = await _activity(session, supplier.id)
    domains = await _domains(session, supplier.id)
    top = (
        await session.execute(
            select(Category.domain, Category.slug, Category.name_en, Category.name_ar, func.count())
            .join(Listing, Listing.category_id == Category.id)
            .where(Listing.supplier_id == supplier.id, _ACTIVE)
            .group_by(Category.id)
            .order_by(func.count().desc(), Category.name_en)
            .limit(TOP_CATEGORIES)
        )
    ).all()
    return {
        "slug": supplier.slug,
        "name": supplier.name,
        "name_ar": supplier.name_ar,
        "area": supplier.area,
        "governorate": supplier.governorate,
        "website_url": supplier.website_url,
        **_summary(supplier, activity, domains),
        "top_categories": [
            {
                "ref": category_ref(domain, cat_slug),
                "name_en": name_en,
                "name_ar": name_ar,
                "count": n,
            }
            for domain, cat_slug, name_en, name_ar, n in top
        ],
    }


@router.get("/suppliers/{slug}/listings")
async def supplier_listings(
    slug: str,
    in_stock: bool = Query(False, description="Only listings the supplier marks in stock"),
    limit: int = Query(24, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> dict:
    supplier = await _get_supplier(session, slug)
    base = select(Listing).where(Listing.supplier_id == supplier.id, _ACTIVE)
    if in_stock:
        base = base.where(_IN_STOCK)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = (
        (
            await session.execute(
                base.options(selectinload(Listing.supplier), selectinload(Listing.category))
                # In stock first: what a buyer can actually get leads the page.
                # Then freshest, and finally id, so a page boundary never falls
                # between two rows the database considers equal — offset paging
                # over an unstable order repeats some rows and skips others.
                .order_by(
                    case((_IN_STOCK, 0), else_=1),
                    Listing.last_verified_at.desc(),
                    Listing.id,
                )
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
        # The shop page lists rows, not details: specs and datasheets are the
        # product page's, and would multiply the payload by up to fifty fields a row.
        "items": [
            ListingRead.model_validate(row).model_dump(mode="json", exclude={"specs", "documents"})
            for row in rows
        ],
    }
