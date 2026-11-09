"""Categories endpoint — the taxonomy with per-category listing counts.

Powers the category browse bar in the UI. Counts are global (active listings),
so they stay stable as the user filters.

Categories are identified by `ref` (`domain:slug`), not by slug alone: slugs are
unique per domain, so "measurement" names both an electronics leaf and a tools
one. Slug is still returned, for display and for URLs that predate refs.
"""

from __future__ import annotations

from app.deps import get_session
from fastapi import APIRouter, Depends, Query
from makhzan_schemas.models import Category, Product, Supplier
from makhzan_schemas.search import category_ref
from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["categories"])


@router.get("/stats")
async def stats(session: AsyncSession = Depends(get_session)) -> dict:
    # Listed products only: a merged-away or withdrawn one keeps its row (its id
    # is permanent) but is not something anyone can find or buy.
    products = await session.scalar(
        select(func.count()).select_from(Product).where(Product.is_listed())
    )
    suppliers = await session.scalar(select(func.count()).select_from(Supplier))
    categories = await session.scalar(
        select(func.count(distinct(Product.category_id))).where(
            Product.category_id.is_not(None), Product.is_listed()
        )
    )
    return {"products": products, "suppliers": suppliers, "categories": categories}


@router.get("/categories")
async def list_categories(
    domain: str | None = Query(
        None, description="Return only this vertical's tree. Omit for the whole taxonomy"
    ),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    counts = dict(
        (
            await session.execute(
                select(Product.category_id, func.count())
                .where(Product.is_listed())
                .group_by(Product.category_id)
            )
        ).all()
    )
    # Parent refs are resolved over the whole taxonomy, not the filtered slice:
    # a scoped request still has to name its parents correctly, and a parent
    # lookup restricted to the slice would silently report None for any category
    # whose parent fell outside it.
    all_cats = (
        (await session.execute(select(Category).order_by(Category.domain, Category.path)))
        .scalars()
        .all()
    )
    id_to_ref = {c.id: category_ref(c.domain, c.slug) for c in all_cats}
    cats = [c for c in all_cats if domain is None or c.domain == domain]
    return [
        {
            "ref": category_ref(c.domain, c.slug),
            "domain": c.domain,
            "slug": c.slug,
            "name_en": c.name_en,
            "name_ar": c.name_ar,
            "parent": id_to_ref.get(c.parent_id),
            "count": counts.get(c.id, 0),
        }
        for c in cats
    ]
