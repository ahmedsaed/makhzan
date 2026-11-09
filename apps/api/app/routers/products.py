"""Product endpoint — a canonical product with all its supplier offers."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from app.deps import get_session
from fastapi import APIRouter, Depends, HTTPException, Query
from makhzan_schemas.contracts import OfferRead, ProductRead, ProductSummary
from makhzan_schemas.enums import ListingStatus
from makhzan_schemas.models import Listing, Product, ProductRedirect
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

logger = logging.getLogger(__name__)

router = APIRouter(tags=["products"])


@router.get("/products/{product_id}", response_model=ProductRead)
async def get_product(
    product_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ProductRead:
    """A product and its active offers.

    Ids are permanent (docs/decisions/0004-stable-product-ids.md). A product
    every shop has withdrawn is still a product: `status = "delisted"`, no
    offers, and the last price range seen. One merged into another is a 404
    here; `/products/{id}/redirect` says where it went.
    """
    product = await session.get(Product, product_id, options=[selectinload(Product.category)])
    if product is None or product.merged_into is not None:
        raise HTTPException(status_code=404, detail="product not found")

    offers = (
        (
            await session.execute(
                select(Listing)
                # An archived listing keeps its product, which is how a withdrawn
                # product still knows its last price; it is not an offer any more.
                .where(Listing.product_id == product_id, Listing.status == ListingStatus.ACTIVE)
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
        status="delisted" if product.delisted_at is not None else "listed",
        delisted_at=product.delisted_at,
        offers=[OfferRead.model_validate(o) for o in offers],
    )


#: How often a redirect's "last used" is written: at most once a day per row,
#: so following a redirect costs a read, not a write, almost every time.
USE_GRANULARITY = timedelta(days=1)


@router.get("/products/{product_id}/redirect")
async def product_redirect(
    product_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> dict:
    """Where a product id that has no page of its own leads, as `{"id": …}`.

    Two kinds (docs/decisions/0005-url-retirement.md): a product merged into
    another (`Product.merged_into`), and an id deleted before ids became
    permanent (`ProductRedirect`). 404 for anything else, a listed or
    withdrawn product included: those have a page of their own.

    Records that the redirect was used, at most once a day, so that one nobody
    follows can be retired after a year. The API's only write.
    """
    now = datetime.now(UTC)
    stale = now - USE_GRANULARITY
    target = await session.scalar(
        select(Product.merged_into).where(
            Product.id == product_id, Product.merged_into.is_not(None)
        )
    )
    if target is not None:
        touch = (
            update(Product)
            .where(
                Product.id == product_id,
                or_(Product.redirect_used_at.is_(None), Product.redirect_used_at < stale),
            )
            .values(redirect_used_at=now)
        )
    else:
        target = await session.scalar(
            select(ProductRedirect.new_id).where(ProductRedirect.old_id == product_id)
        )
        if target is None:
            raise HTTPException(status_code=404, detail="no redirect for this product")
        touch = (
            update(ProductRedirect)
            .where(
                ProductRedirect.old_id == product_id,
                or_(ProductRedirect.last_used_at.is_(None), ProductRedirect.last_used_at < stale),
            )
            .values(last_used_at=now)
        )
    try:
        await session.execute(touch.execution_options(synchronize_session=False))
        await session.commit()
    except SQLAlchemyError:
        # Bookkeeping: a failed write must never cost a reader the redirect.
        await session.rollback()
        logger.warning("could not record a use of redirect %s", product_id, exc_info=True)
    return {"id": str(target)}


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

    Listed products only, whoever asks: a withdrawn product's page leans on this
    rail to send its reader somewhere that still sells the thing.
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
                .where(scope, Product.id != product_id, Product.is_listed())
                .options(selectinload(Product.category))
                .order_by(*order)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)
