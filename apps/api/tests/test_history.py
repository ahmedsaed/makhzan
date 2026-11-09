"""/listings/{id}/history and /products/{id}/history — the recorded change points.

Nothing displays these yet; they exist so the product page's "lowest in 90 days"
and stock history can be built once weeks of data are in. What matters now is
the shape, the window (including the value already in force when it opened) and
the caps that keep the endpoints cheap.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.routers import history
from factories import make_listing, make_product, make_supplier
from makhzan_schemas.enums import StockSignal
from makhzan_schemas.models import PriceObservation


def _ago(days: float) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


async def _observe(db, listing, days_ago, price, stock=StockSignal.IN_STOCK):
    db.add(
        PriceObservation(
            listing_id=listing.id,
            observed_at=_ago(days_ago),
            price=None if price is None else Decimal(price),
            currency="EGP",
            stock_signal=stock,
            in_stock=stock == StockSignal.IN_STOCK,
        )
    )
    await db.commit()


async def test_listing_history_returns_change_points_oldest_first(client, db):
    supplier = await make_supplier(db)
    listing = await make_listing(db, supplier=supplier)
    await _observe(db, listing, 30, "120.00")
    await _observe(db, listing, 10, "135.50", StockSignal.OUT_OF_STOCK)
    await _observe(db, listing, 2, None)

    response = await client.get(f"/listings/{listing.id}/history")

    assert response.status_code == 200
    body = response.json()
    assert body["listing_id"] == str(listing.id)
    assert body["truncated"] is False
    assert [
        {k: p[k] for k in ("price", "currency", "stock_signal", "in_stock")} for p in body["points"]
    ] == [
        {"price": 120.0, "currency": "EGP", "stock_signal": "in_stock", "in_stock": True},
        {"price": 135.5, "currency": "EGP", "stock_signal": "out_of_stock", "in_stock": False},
        {"price": None, "currency": "EGP", "stock_signal": "in_stock", "in_stock": True},
    ]
    times = [datetime.fromisoformat(p["observed_at"]) for p in body["points"]]
    assert times == sorted(times)


async def test_an_archived_stretch_is_marked_unavailable(client, db):
    """So "in stock N of 12 weeks" can clip the weeks the shop did not list it."""
    supplier = await make_supplier(db)
    listing = await make_listing(db, supplier=supplier)
    await _observe(db, listing, 60, "120.00")
    db.add(
        PriceObservation(
            listing_id=listing.id,
            observed_at=_ago(40),
            price=Decimal("120.00"),
            currency="EGP",
            stock_signal=StockSignal.IN_STOCK,
            in_stock=False,
            available=False,
        )
    )
    await db.commit()
    await _observe(db, listing, 10, "120.00")

    body = (await client.get(f"/listings/{listing.id}/history")).json()

    assert [(p["available"], p["in_stock"]) for p in body["points"]] == [
        (True, True),
        (False, False),
        (True, True),
    ]


async def test_the_window_keeps_the_value_in_force_when_it_opened(client, db):
    """A price set 200 days ago and never changed is still the price in the last 90."""
    supplier = await make_supplier(db)
    listing = await make_listing(db, supplier=supplier)
    await _observe(db, listing, 300, "90.00")
    await _observe(db, listing, 200, "100.00")
    await _observe(db, listing, 40, "110.00")

    body = (await client.get(f"/listings/{listing.id}/history?days=90")).json()

    assert [p["price"] for p in body["points"]] == [100.0, 110.0]
    assert datetime.fromisoformat(body["since"]) > _ago(91)


async def test_a_listing_with_no_history_returns_no_points(client, db):
    supplier = await make_supplier(db)
    listing = await make_listing(db, supplier=supplier)

    body = (await client.get(f"/listings/{listing.id}/history")).json()

    assert body["points"] == []
    assert body["truncated"] is False


async def test_history_of_a_missing_listing_or_product_is_404(client):
    assert (await client.get(f"/listings/{uuid.uuid4()}/history")).status_code == 404
    assert (await client.get(f"/products/{uuid.uuid4()}/history")).status_code == 404


async def test_days_is_capped(client, db):
    supplier = await make_supplier(db)
    listing = await make_listing(db, supplier=supplier)

    assert (await client.get(f"/listings/{listing.id}/history?days=0")).status_code == 422
    over = history.MAX_DAYS + 1
    assert (await client.get(f"/listings/{listing.id}/history?days={over}")).status_code == 422
    ok = await client.get(f"/listings/{listing.id}/history?days={history.MAX_DAYS}")
    assert ok.status_code == 200


async def test_points_are_capped_to_the_newest(client, db, monkeypatch):
    monkeypatch.setattr(history, "MAX_POINTS", 3)
    supplier = await make_supplier(db)
    listing = await make_listing(db, supplier=supplier)
    for i, price in enumerate(["10", "11", "12", "13", "14"]):
        await _observe(db, listing, 50 - i, price)

    body = (await client.get(f"/listings/{listing.id}/history")).json()

    assert [p["price"] for p in body["points"]] == [12.0, 13.0, 14.0]
    assert body["truncated"] is True


async def test_product_history_has_one_entry_per_offer(client, db):
    product = await make_product(db)
    other_product = await make_product(db)
    a = await make_listing(db, supplier=await make_supplier(db), product=product)
    b = await make_listing(db, supplier=await make_supplier(db), product=product)
    elsewhere = await make_listing(db, supplier=await make_supplier(db), product=other_product)
    await _observe(db, a, 20, "50.00")
    await _observe(db, a, 5, "45.00")
    await _observe(db, b, 20, "52.00", StockSignal.OUT_OF_STOCK)
    await _observe(db, elsewhere, 20, "999.00")

    response = await client.get(f"/products/{product.id}/history?days=30")

    assert response.status_code == 200
    body = response.json()
    assert body["product_id"] == str(product.id)
    offers = {o["listing_id"]: o for o in body["offers"]}
    assert set(offers) == {str(a.id), str(b.id)}
    assert [p["price"] for p in offers[str(a.id)]["points"]] == [50.0, 45.0]
    assert [p["in_stock"] for p in offers[str(b.id)]["points"]] == [False]
