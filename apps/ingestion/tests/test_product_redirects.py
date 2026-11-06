"""A product id replaced by a regroup redirects to where its offers went.

Product ids are URLs people share and search engines index, but a rebuild
replaces a product whenever its group key changes. `rebuild_products` records
each move in `product_redirects` (docs/decisions/0004-stable-product-ids.md).
"""

from __future__ import annotations

import uuid

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ListingStatus, SourceType
from makhzan_schemas.grouping import rebuild_products
from makhzan_schemas.models import Listing, Product, ProductRedirect, Supplier
from sqlalchemy import select


async def _supplier(slug: str) -> Supplier:
    supplier = Supplier(id=uuid.uuid4(), slug=slug, name=slug, source_type=SourceType.SCRAPED)
    async with SessionLocal() as session:
        session.add(supplier)
        await session.commit()
    return supplier


async def _listing(supplier: Supplier, title: str, part_number: str = "SG90") -> uuid.UUID:
    listing = Listing(
        id=uuid.uuid4(),
        supplier_id=supplier.id,
        source=supplier.slug,
        source_type=SourceType.SCRAPED,
        external_id=str(uuid.uuid4()),
        title_en=title,
        # What normalisation extracts from the title; grouping keys on it.
        part_number=part_number,
        price=100,
        images=[],
        attributes={},
    )
    async with SessionLocal() as session:
        session.add(listing)
        await session.commit()
    return listing.id


async def _rebuild() -> dict:
    async with SessionLocal() as session:
        return await rebuild_products(session)


async def _product_of(listing_id: uuid.UUID) -> uuid.UUID | None:
    async with SessionLocal() as session:
        return await session.scalar(select(Listing.product_id).where(Listing.id == listing_id))


async def _redirects() -> dict[uuid.UUID, uuid.UUID]:
    async with SessionLocal() as session:
        rows = (await session.execute(select(ProductRedirect))).scalars().all()
    return {row.old_id: row.new_id for row in rows}


async def _archive(listing_id: uuid.UUID) -> None:
    async with SessionLocal() as session:
        listing = await session.get(Listing, listing_id)
        listing.status = ListingStatus.ARCHIVED
        await session.commit()


async def test_a_product_replaced_when_a_second_shop_sells_it_redirects():
    shop_a, shop_b = await _supplier("shop-a"), await _supplier("shop-b")
    a = await _listing(shop_a, "SG90 Micro Servo Motor 9g")
    await _rebuild()
    alone = await _product_of(a)

    b = await _listing(shop_b, "SG90 Micro Servo Motor 9g Tower Pro")
    stats = await _rebuild()
    shared = await _product_of(a)

    assert shared != alone, "the test needs the second shop to change the group key"
    assert await _product_of(b) == shared
    assert await _redirects() == {alone: shared}
    assert stats["redirected"] == 1


async def test_a_redirect_stays_one_hop_when_its_target_is_replaced_too():
    shop_a, shop_b = await _supplier("shop-a"), await _supplier("shop-b")
    a = await _listing(shop_a, "SG90 Micro Servo Motor 9g")
    await _rebuild()
    first = await _product_of(a)
    b = await _listing(shop_b, "SG90 Micro Servo Motor 9g Tower Pro")
    await _rebuild()
    second = await _product_of(a)

    # Shop B stops selling it: back to a product of one, under a new id.
    await _archive(b)
    await _rebuild()
    third = await _product_of(a)

    assert len({first, second, third}) == 3
    assert await _redirects() == {first: third, second: third}


async def test_a_product_whose_offers_are_all_gone_takes_its_redirects_with_it():
    shop_a, shop_b = await _supplier("shop-a"), await _supplier("shop-b")
    a = await _listing(shop_a, "SG90 Micro Servo Motor 9g")
    await _rebuild()
    b = await _listing(shop_b, "SG90 Micro Servo Motor 9g Tower Pro")
    await _rebuild()
    assert len(await _redirects()) == 1

    await _archive(a)
    await _archive(b)
    stats = await _rebuild()

    # Nowhere to send anyone: no redirect, so the page is a plain 404.
    assert await _redirects() == {}
    assert stats["redirected"] == 0
    async with SessionLocal() as session:
        assert (await session.execute(select(Product))).scalars().all() == []


async def test_an_unchanged_rebuild_records_nothing():
    shop_a = await _supplier("shop-a")
    a = await _listing(shop_a, "SG90 Micro Servo Motor 9g")
    await _rebuild()
    before = await _product_of(a)
    stats = await _rebuild()

    assert await _product_of(a) == before
    assert await _redirects() == {}
    assert stats["redirected"] == 0
