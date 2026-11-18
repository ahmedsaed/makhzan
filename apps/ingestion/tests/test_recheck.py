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


async def test_a_shop_hiding_out_of_stock_keeps_the_marker_for_its_unlisted_pass(woo):  # noqa: F811
    """`include` omits a hidden out-of-stock product: "not returned" is no answer
    there, so the marker stays until the unlisted pass reads its stock."""
    from makhzan_schemas.models import Supplier
    from worker import pipeline

    woo.catalogue = {1: "instock", 2: "instock"}
    await _run_until_cycle()
    listing = await _mark("2")
    del woo.catalogue[2]  # out of stock, and hidden by the shop

    adapter = _woo_adapter()
    partitions = adapter.partitions()
    adapter.hides_out_of_stock = True
    adapter.partitions = lambda: partitions  # the fake shop has no unlisted route
    run = await run_source("woo", adapter)
    assert run.stats["recheck"] == {
        "asked": 1,
        "read": 0,
        "absent": 0,
        "hidden_kept": 1,
        "unasked": 0,
    }
    assert await _marker(listing) is not None

    # The unlisted pass reads it by id, out of stock: that answers it.
    async with SessionLocal() as session:
        supplier_id = await session.scalar(select(Supplier.id).where(Supplier.slug == "woo"))
        assert await pipeline._mark_out_of_stock(session, supplier_id, ["2"]) == 1
        await session.commit()
    assert await _marker(listing) is None


async def test_a_host_refusing_the_re_check_stops_the_run(woo):  # noqa: F811
    """A Retry-After longer than the crawler waits, met on the re-check's request,
    stops the run there with that reason: no partition is tried after it."""
    import time

    from worker import http as http_mod

    woo.catalogue = {1: "instock", 2: "instock"}
    await _run_until_cycle()
    listing = await _mark("2")
    pages_before = sum(1 for p in woo.requests if "stock_status" in p)
    http_mod._NOT_BEFORE["https://woo.test"] = time.monotonic() + http_mod.RETRY_AFTER_CAP * 2

    run = await run_source("woo", _woo_adapter())
    assert run.stats["stopped"].startswith("refused by its host")
    assert "failed" in run.stats["recheck"]
    # One error, the re-check's: no partition was tried after the refusal.
    assert [e.split(":")[0] for e in run.stats["errors"]] == ["re-check first"]
    assert sum(1 for p in woo.requests if "stock_status" in p) == pages_before
    assert await _marker(listing) is not None


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


async def test_a_details_shop_waits_for_its_sweep_which_reads_the_price(monkeypatch):
    """A product page never writes price or stock (owner, 2026-11-17): a shop
    whose details stage is on is honoured at its partition's turn, the stage
    neither puts the marked listing first nor clears it, and the sweep that does
    clear it really re-reads the price."""
    import test_details as td

    from worker import details
    from worker import http as http_mod
    from worker import robots as robots_mod

    clock = td._Clock()
    monkeypatch.setattr(robots_mod, "ROBOTS", td._AllowAll())
    monkeypatch.setattr(http_mod.asyncio, "sleep", clock.sleep)
    monkeypatch.setattr(http_mod, "_now", clock)

    class PricedShop(td._Shop):
        prices = {"a": "10 EGP", "b": "10 EGP", "c": "10 EGP"}

        async def fetch_page(self, partition, page):
            result = await super().fetch_page(partition, page)
            for raw in result.items:
                raw.price_text = self.prices[raw.external_id]
            return result

    shop = PricedShop({"a": "t1", "b": "t1", "c": "t1"}, per_run=1)
    monkeypatch.setattr(
        http_mod, "make_client", lambda **kw: httpx.AsyncClient(transport=shop.transport(), **kw)
    )
    assert recheck.how(shop) == recheck.PARTITION
    await run_source(shop.source_id, shop)
    read = {p.rsplit("/", 1)[-1] for p in shop.details_sent()}
    marked = sorted({"a", "b", "c"} - read)[-1]
    listing = await _mark(marked)

    async with SessionLocal() as session:
        due = await details.due_listings(session, shop.source_id, shop.details)
        assert all(why != "recheck" for _, why in due)

        # The details stage alone reads the page but answers nothing.
        async def no_pace():
            return 0.0

        import dataclasses

        shop.details = dataclasses.replace(shop.details, per_run=3)
        await details.run_details(session, shop, errors=[], pace=no_pace, already_sent=False)
    assert f"/p/{marked}" in shop.details_sent()
    assert await _marker(listing) is not None, "a product page is no answer to a price report"

    shop.prices[marked] = "25 EGP"  # what the visitor said, true in the shop
    await run_source(shop.source_id, shop)
    async with SessionLocal() as session:
        row = await session.get(Listing, listing)
    assert str(row.price) == "25.00" and row.recheck_requested_at is None


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


async def test_an_archived_listing_is_never_left_waiting():
    """Archived, nothing would read it: archiving clears its marker, and it is
    neither marked again nor listed as pending."""
    from sqlalchemy import func, update

    await run_source(SRC, StubAdapter())  # a1 a2 b1 b2 c1: one whole cycle
    listing = await _mark("b1")
    # The next cycle no longer lists b1: the cycle's end archives it.
    await run_source(SRC, StubAdapter(pages={1: ["a1", "a2"], 2: ["b2"], 3: ["c1"]}))
    async with SessionLocal() as session:
        row = await session.get(Listing, listing)
        assert row.status == ListingStatus.ARCHIVED and row.recheck_requested_at is None
        assert await recheck.request(session, [listing]) == 0
        # Even a marker left on an archived row (set before this rule) is not pending.
        await session.execute(
            update(Listing).where(Listing.id == listing).values(recheck_requested_at=func.now())
        )
        await session.commit()
        assert await recheck.pending(session) == []
        assert await recheck.due(session, SRC) == []
