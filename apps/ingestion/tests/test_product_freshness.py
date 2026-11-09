"""A product is as fresh as its freshest offer.

The stale filter (rule C2b) hides products whose search document says
`last_verified_at` is more than 45 days old. That document carries the newest
check of any listing, so a product one reachable shop re-checked yesterday
stays visible even when an unreachable shop's offer on it is months old: the
same "any" that `in_stock` aggregates with.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import SourceType, StockSignal
from makhzan_schemas.grouping import rebuild_products
from makhzan_schemas.models import Listing, Product, Supplier
from sqlalchemy import select

OLD = datetime(2026, 8, 1, tzinfo=UTC)
NEW = datetime(2026, 11, 1, tzinfo=UTC)


async def _listing(slug: str, verified: datetime, stock: StockSignal) -> None:
    supplier = Supplier(id=uuid.uuid4(), slug=slug, name=slug, source_type=SourceType.SCRAPED)
    listing = Listing(
        id=uuid.uuid4(),
        supplier_id=supplier.id,
        source=slug,
        source_type=SourceType.SCRAPED,
        external_id="1",
        title_en="SG90 Micro Servo",
        part_number="SG90",
        price=100,
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
