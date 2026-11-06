"""Product endpoint — a canonical product with all its supplier offers."""

from __future__ import annotations

import uuid

from app.deps import get_session
from fastapi import APIRouter, Depends, HTTPException, Query
from makhzan_schemas.contracts import OfferRead, ProductRead, ProductSummary
from makhzan_schemas.models import Listing, Product
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

router = APIRouter(tags=["products"])


@router.get("/products/{product_id}", response_model=ProductRead)
async def get_product(
    product_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ProductRead:
    product = await session.get(Product, product_id, options=[selectinload(Product.category)])
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")

    offers = (
        (
            await session.execute(
                select(Listing)
                .where(Listing.product_id == product_id)
                .options(selectinload(Listing.supplier))
            )
        )
        .scalars()
        .all()
    )
    # Cheapest first; priceless offers last.
    offers = sorted(offers, key=lambda o: (o.price is None, o.price or 0))

    return ProductRead(
        id=product.id,
        part_number=product.part_number,
        title_en=product.title_en,
        title_ar=product.title_ar,
        brand=product.brand,
        image=product.image,
        supplier_count=product.supplier_count,
        offer_count=product.offer_count,
        min_price=product.min_price,
        max_price=product.max_price,
        currency=product.currency,
        in_stock=product.in_stock,
        last_verified_at=product.last_verified_at,
        category=product.category,
        offers=[OfferRead.model_validate(o) for o in offers],
    )


@router.get("/products/{product_id}/similar", response_model=list[ProductSummary])
async def similar_products(
    product_id: uuid.UUID,
    limit: int = Query(8, ge=1, le=24),
    session: AsyncSession = Depends(get_session),
) -> list[Product]:
    """Other products a buyer looking at this one might mean instead.

    Same category, nearest price first. Category is the strongest signal we have:
    the taxonomy is curated per domain, so "same leaf" already means "same kind of
    thing" far more reliably than any title similarity we could compute here.
    Price then separates a 9g hobby servo from an industrial one.

    Deliberately not a recommender. There is no behavioural data to build one
    from, and a wrong "similar" on a parts catalogue sends someone to the wrong
    component.
    """
    product = await session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")

    # Uncategorized products fall back to their vertical — weaker, but a page
    # with nothing on it is worse than a page with loosely related stock.
    scope = (
        Product.category_id == product.category_id
        if product.category_id is not None
        else Product.domain == product.domain
    )

    if product.min_price is None:
        # No price to be near; lead with the products most suppliers carry.
        order = (Product.supplier_count.desc(), Product.offer_count.desc())
    else:
        # NULLs last: an unpriced product is not "close" to any price.
        distance = func.abs(Product.min_price - product.min_price)
        order = (Product.min_price.is_(None), distance.asc())

    rows = (
        (
            await session.execute(
                select(Product)
                .where(scope, Product.id != product_id)
                .options(selectinload(Product.category))
                .order_by(*order)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)
