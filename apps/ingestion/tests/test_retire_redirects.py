"""Redirects nobody follows for a year are dropped (docs/decisions/0005-url-retirement.md).

Both kinds that are data: a merged-away product's row, and an id deleted before
ids were permanent (`product_redirects`). "Unused" counts from the last time the
redirect was followed, or from its creation if it never has been.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ProductEventKind
from makhzan_schemas.models import Product, ProductRedirect
from sqlalchemy import select, update
from test_product_ids import (
    _events,
    _listing,
    _product,
    _product_of,
    _products,
    _rebuild,
    _rules,
    _supplier,
)

from worker.retire_redirects import retire_unused_redirects


@pytest.mark.parametrize("used_days_ago, retired", [(None, True), (400, True), (30, False)])
async def test_a_redirect_unused_for_a_year_is_retired(monkeypatch, used_days_ago, retired):
    now = datetime(2027, 6, 1, tzinfo=UTC)
    shop_a, shop_b = await _supplier("shop-a"), await _supplier("shop-b")
    _rules(monkeypatch, {"A": "x", "B": "y"})
    a = await _listing(shop_a, "A")
    b = await _listing(shop_b, "B")
    await _rebuild()
    pa, pb = await _product_of(a), await _product_of(b)
    _rules(monkeypatch, {"A": "xy", "B": "xy"})
    await _rebuild()
    absorbed = pb if (await _product(pb)).merged_into else pa
    survivor = pa if absorbed == pb else pb
    legacy = uuid.uuid4()
    used = None if used_days_ago is None else now - timedelta(days=used_days_ago)
    async with SessionLocal() as session:
        session.add(
            ProductRedirect(
                old_id=legacy,
                new_id=survivor,
                created_at=now - timedelta(days=500),
                last_used_at=used,
            )
        )
        await session.execute(
            update(Product)
            .where(Product.id == absorbed)
            .values(merged_at=now - timedelta(days=500), redirect_used_at=used)
        )
        await session.commit()

    async with SessionLocal() as session:
        counts = await retire_unused_redirects(session, now=now)

    assert counts == {"merged_products": int(retired), "product_redirects": int(retired)}
    products = await _products()
    assert (absorbed not in products) is retired
    assert survivor in products, "only the redirect goes, never the product it leads to"
    async with SessionLocal() as session:
        left = await session.scalar(select(ProductRedirect).where(ProductRedirect.old_id == legacy))
    assert (left is None) is retired
    # The audit trail outlives the row.
    assert (ProductEventKind.MERGE, absorbed, survivor) in await _events()


async def test_a_young_redirect_never_used_is_kept(monkeypatch):
    shop_a = await _supplier("shop-a")
    a = await _listing(shop_a, "SG90 Micro Servo Motor 9g")
    await _rebuild()
    async with SessionLocal() as session:
        session.add(ProductRedirect(old_id=uuid.uuid4(), new_id=await _product_of(a)))
        await session.commit()

    async with SessionLocal() as session:
        counts = await retire_unused_redirects(session)

    assert counts == {"merged_products": 0, "product_redirects": 0}
