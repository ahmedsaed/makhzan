"""Retiring a source: everything it put in the database goes, nothing else does."""

from __future__ import annotations

import uuid

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ReviewReason, SourceType
from makhzan_schemas.models import (
    IngestionRun,
    Listing,
    Product,
    ReviewQueueItem,
    Source,
    SourceCursor,
    Supplier,
)
from sqlalchemy import func, select

from worker.sources.retire import plan, retire


def _supplier(slug):
    return Supplier(id=uuid.uuid4(), slug=slug, name=slug, source_type=SourceType.SCRAPED)


def _listing(source, supplier):
    return Listing(
        id=uuid.uuid4(),
        supplier_id=supplier.id,
        source=source,
        source_type=SourceType.SCRAPED,
        external_id=str(uuid.uuid4()),
        title_en=f"item from {source}",
        images=[],
        attributes={},
    )


async def _seed():
    """Two sources. `old` has its own supplier and shares a second with `shop-a`."""
    own, shared = _supplier("old-shop"), _supplier("shared-shop")
    rows = [own, shared]
    for source in ("old", "shop-a"):
        rows += [
            Source(source_id=source, adapter="fixture", supplier={"slug": source}, config={}),
            IngestionRun(source=source, source_type=SourceType.SCRAPED),
            SourceCursor(source=source, partition_key=""),
            ReviewQueueItem(source=source, reason=ReviewReason.MISSING_PRICE, raw_payload={}),
        ]
    rows += [_listing("old", own), _listing("old", shared), _listing("shop-a", shared)]
    async with SessionLocal() as session:
        session.add_all(rows[:2])
        await session.flush()
        session.add_all(rows[2:])
        await session.commit()


async def _count(model, **where):
    query = select(func.count()).select_from(model).filter_by(**where)
    async with SessionLocal() as session:
        return (await session.execute(query)).scalar_one()


async def test_plan_reports_and_changes_nothing():
    await _seed()
    async with SessionLocal() as session:
        found = await plan(session, "old")

    assert found == {
        "listings": 2,
        "ingestion_runs": 1,
        "source_cursors": 1,
        "review_queue": 1,
        "sources": 1,
        "suppliers": ["old-shop"],
    }
    assert await _count(Listing, source="old") == 2


async def test_retire_removes_the_source_and_leaves_the_rest():
    await _seed()
    async with SessionLocal() as session:
        await retire(session, "old")

    for model in (Listing, IngestionRun, SourceCursor, ReviewQueueItem):
        assert await _count(model, source="old") == 0, model.__name__
        assert await _count(model, source="shop-a") == 1, model.__name__
    assert await _count(Source, source_id="old") == 0
    assert await _count(Source, source_id="shop-a") == 1
    # Its own supplier goes; the one another source still lists under stays.
    assert await _count(Supplier, slug="old-shop") == 0
    assert await _count(Supplier, slug="shared-shop") == 1


async def test_an_unknown_source_plans_nothing():
    async with SessionLocal() as session:
        found = await plan(session, "never-existed")
    assert not any(found.values())


async def test_retire_deletes_the_products_only_it_offered():
    """A regroup never deletes a product (its id is permanent), but a source
    being retired should never have been listed: its own products go with it,
    and one another source also offered stays."""
    own, shared = _supplier("old-shop"), _supplier("shop-a")
    mine = Product(id=uuid.uuid4(), group_key="single:old:1")
    both = Product(id=uuid.uuid4(), group_key="mpn:X")
    # Merged into one of its products: it only redirects there, so it goes too.
    merged = Product(id=uuid.uuid4(), group_key="single:old:2", merged_into=mine.id)
    async with SessionLocal() as session:
        session.add_all([own, shared, mine, both])
        await session.flush()
        session.add(merged)
        await session.flush()
        for source, supplier, product in (
            ("old", own, mine),
            ("old", own, both),
            ("shop-a", shared, both),
        ):
            listing = _listing(source, supplier)
            listing.product_id = product.id
            session.add(listing)
        await session.commit()

    async with SessionLocal() as session:
        await retire(session, "old")

    assert await _count(Product, id=mine.id) == 0
    assert await _count(Product, id=merged.id) == 0
    assert await _count(Product, id=both.id) == 1
