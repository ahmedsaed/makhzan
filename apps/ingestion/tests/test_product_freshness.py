"""A product is as fresh as its freshest offer.

The stale filter (rule C2b) hides products whose search document says
`last_verified_at` is more than 45 days old. That document carries the newest
check of any listing, so a product one reachable shop re-checked yesterday
stays visible even when an unreachable shop's offer on it is months old: the
same "any" that `in_stock` aggregates with.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import SourceType, StockSignal
from makhzan_schemas.grouping import rebuild_products
from makhzan_schemas.models import Listing, Product, Supplier
from sqlalchemy import select

OLD = datetime(2026, 8, 1, tzinfo=UTC)
NEW = datetime(2026, 11, 1, tzinfo=UTC)


async def _listing(slug: str, verified: datetime, stock: StockSignal, price: int = 100) -> None:
    supplier = Supplier(id=uuid.uuid4(), slug=slug, name=slug, source_type=SourceType.SCRAPED)
    listing = Listing(
        id=uuid.uuid4(),
        supplier_id=supplier.id,
        source=slug,
        source_type=SourceType.SCRAPED,
        external_id="1",
        title_en="SG90 Micro Servo",
        part_number="SG90",
        price=price,
        stock_signal=stock,
        images=[],
        attributes={},
        last_verified_at=verified,
    )
    async with SessionLocal() as session:
        session.add(supplier)
        await session.flush()
        session.add(listing)
        await session.commit()


async def test_the_newest_check_of_any_offer_is_the_products():
    await _listing("stale-shop", OLD, StockSignal.IN_STOCK)
    await _listing("fresh-shop", NEW, StockSignal.OUT_OF_STOCK)

    async with SessionLocal() as session:
        await rebuild_products(session)
        await session.commit()
        (product,) = (await session.execute(select(Product))).scalars().all()

    assert product.supplier_count == 2
    assert product.last_verified_at == NEW
    # Freshness and stock aggregate independently: in stock (at the stale
    # shop) and fresh (at the other) are both true, and each filter reads its own.
    assert product.in_stock is True


async def test_a_card_quotes_the_fresh_offers_price_not_a_stale_cheaper_one():
    """The card, the price sort and the price filter read min/max_price. A
    stale shop's cheaper price must not stand in for the fresh one the
    product page leads with."""
    now = datetime.now(UTC)
    await _listing("stale-shop", now - timedelta(days=80), StockSignal.IN_STOCK, price=120)
    await _listing("fresh-shop", now - timedelta(days=1), StockSignal.IN_STOCK, price=300)

    async with SessionLocal() as session:
        await rebuild_products(session)
        await session.commit()
        (product,) = (await session.execute(select(Product))).scalars().all()

    assert (product.min_price, product.max_price) == (300, 300)


async def test_with_no_fresh_offer_the_card_quotes_every_offer():
    now = datetime.now(UTC)
    await _listing("shop-a", now - timedelta(days=80), StockSignal.IN_STOCK, price=120)
    await _listing("shop-b", now - timedelta(days=90), StockSignal.IN_STOCK, price=150)

    async with SessionLocal() as session:
        await rebuild_products(session)
        await session.commit()
        (product,) = (await session.execute(select(Product))).scalars().all()

    assert (product.min_price, product.max_price) == (120, 150)
