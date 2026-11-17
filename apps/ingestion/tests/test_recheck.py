"""Re-check first (worker/recheck.py): a listing a person asked to be read before its turn.

Owner decision (2026-11-17): accepting a "wrong price or stock" report marks
the ticked offers; the next full run of each one's shop reads it first, in the
way its adapter can, within its pace, robots.txt and page ceiling, and any full
read clears the marker. The shops and listings are fictional.
"""

from __future__ import annotations

import uuid

import httpx
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ListingStatus, StockSignal
from makhzan_schemas.models import Listing, Report, Source
from sqlalchemy import select
from test_crawl_phase1 import _run_until_cycle, _status_of, _woo_adapter
from test_crawl_phase1 import allow_robots, woo  # noqa: F401 — fixtures
from test_pipeline import SRC, StubAdapter
from worker import pause, recheck
from worker import reports as reports_cli
from worker.pipeline import run_source


async def _mark(external_id: str) -> uuid.UUID:
    async with SessionLocal() as session:
        listing = await session.scalar(select(Listing).where(Listing.external_id == external_id))
        assert await recheck.request(session, [listing.id]) == 1
        await session.commit()
        return listing.id


async def _marker(listing_id: uuid.UUID):
    async with SessionLocal() as session:
        return (await session.get(Listing, listing_id)).recheck_requested_at


async def test_a_woocommerce_shop_re_reads_a_marked_listing_first_by_id(woo):  # noqa: F811
    woo.catalogue = {1: "instock", 2: "instock"}
    await _run_until_cycle()
    listing = await _mark("2")
    woo.catalogue[2] = "outofstock"  # what the visitor said, true in the shop
    asked_before = len(woo.included())

    run = await run_source("woo", _woo_adapter())
    assert len(woo.included()) == asked_before + 1
    assert woo.included()[-1] == "2"
    assert run.stats["recheck"] == {"asked": 1, "read": 1, "absent": 0, "unasked": 0}
    assert run.stats["requests"]["recheck"] == 1
    row = await _status_of("2")
    assert row.stock_signal == StockSignal.OUT_OF_STOCK
    assert row.recheck_requested_at is None and await _marker(listing) is None


async def test_a_marked_listing_the_shop_no_longer_lists_is_cleared_not_archived(woo):  # noqa: F811
    woo.catalogue = {1: "instock", 2: "instock"}
    await _run_until_cycle()
    listing = await _mark("2")
    del woo.catalogue[2]
    run = await run_source("woo", _woo_adapter())
    assert run.stats["recheck"]["absent"] == 1
    assert await _marker(listing) is None
    assert (await _status_of("2")).status == ListingStatus.ACTIVE  # the cycle decides


async def test_a_paused_shop_and_a_limit_run_ask_nothing(woo):  # noqa: F811
    async with SessionLocal() as session:
        session.add(
            Source(source_id="woo", adapter="fixture", supplier={"slug": "woo", "name": "Woo"})
        )
        await session.commit()
    woo.catalogue = {1: "instock", 2: "instock"}
    await _run_until_cycle()
    listing = await _mark("2")
    asked = len(woo.included())

    limited = await run_source("woo", _woo_adapter(), limit=1)
    assert "recheck" not in limited.stats

    async with SessionLocal() as session:
        await pause.pause_source(session, "woo", by="tester")
        await session.commit()
    paused = await run_source("woo", _woo_adapter())
    assert "recheck" not in paused.stats
    assert len(woo.included()) == asked
    assert await _marker(listing) is not None, "still waiting for the shop to be resumed"


async def test_a_shop_without_a_reader_clears_the_marker_when_its_partition_comes(monkeypatch):
    adapter = StubAdapter()
    assert recheck.how(adapter) == recheck.PARTITION
    await run_source(SRC, adapter)
    listing = await _mark("b1")
    async with SessionLocal() as session:
        (pending,) = await recheck.pending(session)
    assert (pending["source"], pending["count"]) == (SRC, 1)
    run = await run_source(SRC, StubAdapter())
    assert "recheck" not in run.stats  # no early read for this shop
    assert await _marker(listing) is None  # the sweep read it


async def test_a_details_shop_reads_the_marked_page_first(monkeypatch):
    """Where the listing's partition is not swept this run, the details stage
    reads its page before any other, and that read clears the marker. (When the
    sweep does reach it, its card's price and stock answer the report first.)"""
    import test_details as td

    from worker import details
    from worker import http as http_mod
    from worker import robots as robots_mod

    clock = td._Clock()
    monkeypatch.setattr(robots_mod, "ROBOTS", td._AllowAll())
    monkeypatch.setattr(http_mod.asyncio, "sleep", clock.sleep)
    monkeypatch.setattr(http_mod, "_now", clock)
    shop = td._Shop({"a": "t1", "b": "t1", "c": "t1"}, per_run=1)
    monkeypatch.setattr(
        http_mod, "make_client", lambda **kw: httpx.AsyncClient(transport=shop.transport(), **kw)
    )
    assert recheck.how(shop) == recheck.DETAILS
    await run_source(shop.source_id, shop)  # the listings, and one page read
    read = {p.rsplit("/", 1)[-1] for p in shop.details_sent()}
    marked = sorted({"a", "b", "c"} - read)[-1]
    listing = await _mark(marked)

    async def no_pace():
        return 0.0

    async with SessionLocal() as session:
        due = await details.due_listings(session, shop.source_id, shop.details)
        assert [(row.external_id, why) for row, why in due] == [(marked, "recheck")]
        await details.run_details(session, shop, errors=[], pace=no_pace, already_sent=False)
    assert shop.details_sent()[-1] == f"/p/{marked}"
    assert await _marker(listing) is None


async def test_the_cli_accept_marks_too_and_make_status_says_what_waits(capsys):
    await run_source(SRC, StubAdapter())
    async with SessionLocal() as session:
        listing = await session.scalar(select(Listing).where(Listing.external_id == "a1"))
        report = Report(
            product_id=uuid.uuid4(),
            reason="wrong_price_stock",
            offer_ids=[str(listing.id)],
            snapshot={"product": {"title": "Item a1", "listings": []}},
        )
        session.add(report)
        await session.commit()
    assert await reports_cli.run(["accept", str(report.id)]) == 0
    assert "marked 1 listing(s) to be re-read first" in capsys.readouterr().out
    assert await _marker(listing.id) is not None

    from worker import status

    async with SessionLocal() as session:
        await status.rechecks(session)
    out = capsys.readouterr().out
    assert "RE-CHECKS" in out and SRC in out and "1 waiting" in out
