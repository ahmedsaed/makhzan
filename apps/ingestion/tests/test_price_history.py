"""Price and stock history: a row per change, never per recheck.

A crawl overwrites a listing's price and stock, so `price_observations` is the
only place what it used to cost survives. These pin the write rule: a first row
when a listing is stored, one more whenever its price or stock moves, none for a
recheck that finds nothing new, and none from a `limit=` run.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from makhzan_schemas.contracts import RawItem
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ListingStatus, SourceType, StockSignal
from makhzan_schemas.models import Listing, PriceObservation
from sqlalchemy import delete, select
from worker.pipeline import run_source
from worker.sources.base import Page, SourceAdapter, SupplierInfo

SRC = "history-shop"


class Shop(SourceAdapter):
    """One page of scripted items: {external_id: (price_text, availability_text)}."""

    source_id = SRC
    source_type = SourceType.SCRAPED
    supplier = SupplierInfo(slug=SRC, name="History Shop")
    polite_delay = 0

    def __init__(self, items: dict, out_of_stock_ids: list[str] | None = None):
        self.items = items
        self.out_of_stock_ids = out_of_stock_ids or []

    async def fetch_page(self, partition: str, page: int) -> Page:
        return Page(
            [
                RawItem(
                    source=SRC,
                    external_id=ext,
                    title=f"Arduino Uno R3 board {ext}",
                    price_text=price,
                    availability_text=stock,
                )
                for ext, (price, stock) in self.items.items()
            ],
            has_more=False,
            out_of_stock_ids=self.out_of_stock_ids,
        )


async def _observations(external_id: str = "a1") -> list[PriceObservation]:
    async with SessionLocal() as s:
        return (
            (
                await s.execute(
                    select(PriceObservation)
                    .join(Listing, Listing.id == PriceObservation.listing_id)
                    .where(Listing.external_id == external_id)
                    .order_by(PriceObservation.observed_at)
                )
            )
            .scalars()
            .all()
        )


@pytest.mark.asyncio
async def test_first_store_writes_one_row():
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}))

    [row] = await _observations()
    assert row.price == Decimal("120.00")
    assert row.currency == "EGP"
    assert row.stock_signal == StockSignal.IN_STOCK
    assert row.in_stock is True


@pytest.mark.asyncio
async def test_an_unchanged_recheck_writes_nothing():
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}))
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}))
    await run_source(SRC, Shop({"a1": ("120.00 EGP", "In stock")}))

    assert len(await _observations()) == 1


@pytest.mark.asyncio
async def test_a_price_change_writes_one_row():
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}))
    await run_source(SRC, Shop({"a1": ("135 EGP", "In stock")}))

    rows = await _observations()
    assert [r.price for r in rows] == [Decimal("120.00"), Decimal("135.00")]
    assert rows[0].observed_at < rows[1].observed_at


@pytest.mark.asyncio
async def test_a_price_disappearing_is_a_change():
    """'Price on request' is a value of its own, not a gap in the history."""
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}))
    await run_source(SRC, Shop({"a1": (None, "In stock")}))

    assert [r.price for r in await _observations()] == [Decimal("120.00"), None]


@pytest.mark.asyncio
async def test_a_stock_change_writes_one_row():
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}))
    await run_source(SRC, Shop({"a1": ("120 EGP", "Out of stock")}))

    rows = await _observations()
    assert [(r.stock_signal, r.in_stock) for r in rows] == [
        (StockSignal.IN_STOCK, True),
        (StockSignal.OUT_OF_STOCK, False),
    ]


@pytest.mark.asyncio
async def test_only_the_listing_that_changed_gets_a_row():
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock"), "b1": ("50 EGP", "In stock")}))
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock"), "b1": ("55 EGP", "In stock")}))

    assert len(await _observations("a1")) == 1
    assert len(await _observations("b1")) == 2


@pytest.mark.asyncio
async def test_a_limited_run_writes_no_history():
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}), limit=10)

    assert await _observations() == []


@pytest.mark.asyncio
async def test_a_change_a_limited_run_saw_is_recorded_by_the_next_real_run():
    """Compared against the last observation, not the row the limited run overwrote."""
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}))
    await run_source(SRC, Shop({"a1": ("135 EGP", "In stock")}), limit=10)
    assert len(await _observations()) == 1

    await run_source(SRC, Shop({"a1": ("135 EGP", "In stock")}))

    assert [r.price for r in await _observations()] == [Decimal("120.00"), Decimal("135.00")]


@pytest.mark.asyncio
async def test_the_out_of_stock_pass_writes_on_the_flip():
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}))
    # The feed now leaves a1 out, and the by-id route says it is out of stock.
    await run_source(SRC, Shop({}, out_of_stock_ids=["a1"]))

    rows = await _observations()
    assert [(r.price, r.stock_signal) for r in rows] == [
        (Decimal("120.00"), StockSignal.IN_STOCK),
        (Decimal("120.00"), StockSignal.OUT_OF_STOCK),
    ]

    # Still out of stock on the next sweep: nothing new to say.
    await run_source(SRC, Shop({}, out_of_stock_ids=["a1"]))
    assert len(await _observations()) == 2


@pytest.mark.asyncio
async def test_the_out_of_stock_pass_writes_nothing_in_a_limited_run():
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}))
    await run_source(SRC, Shop({}, out_of_stock_ids=["a1"]), limit=10)

    assert len(await _observations()) == 1


@pytest.mark.asyncio
async def test_a_listing_archived_before_history_began_gets_a_first_row():
    """The seed covers active listings only; one that comes back starts its history."""
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}))
    async with SessionLocal() as s:
        await s.execute(delete(PriceObservation))
        listing = (await s.execute(select(Listing))).scalar_one()
        listing.status = ListingStatus.ARCHIVED
        await s.commit()

    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}))

    assert len(await _observations()) == 1


@pytest.mark.asyncio
async def test_deleting_a_listing_deletes_its_history():
    await run_source(SRC, Shop({"a1": ("120 EGP", "In stock")}))
    await run_source(SRC, Shop({"a1": ("135 EGP", "In stock")}))
    assert len(await _observations()) == 2

    async with SessionLocal() as s:
        await s.execute(delete(Listing))
        await s.commit()
    async with SessionLocal() as s:
        assert (await s.execute(select(PriceObservation))).scalars().all() == []
