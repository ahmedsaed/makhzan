"""`Product.content_changed_at` moves only when what a reader sees changes.

It is the sitemap's lastmod, and Google ignores a lastmod that is not
"consistently and verifiably accurate": a daily recheck that found everything
as it was must leave it alone, or every product claims to change every day.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import SourceType, StockSignal
from makhzan_schemas.grouping import rebuild_products
from makhzan_schemas.models import Listing, Product, Supplier
from sqlalchemy import select, update

LONG_AGO = datetime(2026, 1, 1, tzinfo=UTC)


async def _one_listing() -> uuid.UUID:
    supplier = Supplier(
        id=uuid.uuid4(), slug="shop-a", name="Shop A", source_type=SourceType.SCRAPED
    )
    listing = Listing(
        id=uuid.uuid4(),
        supplier_id=supplier.id,
        source=supplier.slug,
        source_type=SourceType.SCRAPED,
        external_id="1",
        title_en="SG90 Micro Servo",
        part_number="SG90",
        price=100,
        stock_signal=StockSignal.IN_STOCK,
        images=["https://shop-a.test/sg90.jpg"],
        attributes={},
        last_verified_at=LONG_AGO,
    )
    async with SessionLocal() as session:
        session.add(supplier)
        await session.flush()
        session.add(listing)
        await session.commit()
    return listing.id


async def _rebuild() -> dict:
    async with SessionLocal() as session:
        return await rebuild_products(session)


async def _product() -> Product:
    async with SessionLocal() as session:
        return (await session.execute(select(Product))).scalar_one()


async def _backdate() -> None:
    """Pretend the product last changed long ago, so a bump is visible."""
    async with SessionLocal() as session:
        await session.execute(update(Product).values(content_changed_at=LONG_AGO))
        await session.commit()


async def _set_listing(listing_id: uuid.UUID, **values) -> None:
    async with SessionLocal() as session:
        await session.execute(update(Listing).where(Listing.id == listing_id).values(**values))
        await session.commit()


async def test_set_when_a_product_is_created():
    started = datetime.now(UTC)
    await _one_listing()

    result = await _rebuild()

    product = await _product()
    assert product.content_changed_at >= started - timedelta(seconds=1)
    assert result["changed"] == 1


async def test_an_identical_rebuild_leaves_it_alone():
    await _one_listing()
    await _rebuild()
    await _backdate()

    result = await _rebuild()

    assert (await _product()).content_changed_at == LONG_AGO
    assert result["changed"] == 0


async def test_a_recheck_that_changed_nothing_leaves_it_alone():
    """last_verified_at moves on every sweep; that alone is not a change."""
    listing_id = await _one_listing()
    await _rebuild()
    await _backdate()
    await _set_listing(listing_id, last_verified_at=datetime.now(UTC))

    await _rebuild()

    product = await _product()
    assert product.last_verified_at > LONG_AGO
    assert product.content_changed_at == LONG_AGO


async def test_bumped_by_a_price_change():
    listing_id = await _one_listing()
    await _rebuild()
    await _backdate()
    await _set_listing(listing_id, price=120)

    result = await _rebuild()

    assert (await _product()).content_changed_at > LONG_AGO
    assert result["changed"] == 1


async def test_bumped_by_a_stock_change():
    listing_id = await _one_listing()
    await _rebuild()
    await _backdate()
    await _set_listing(listing_id, stock_signal=StockSignal.OUT_OF_STOCK)

    await _rebuild()

    assert (await _product()).content_changed_at > LONG_AGO
