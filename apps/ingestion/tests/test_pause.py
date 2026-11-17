"""Pausing the crawl, all of it or one shop, from the database (worker/pause.py).

The admin dashboard and `./makhzan crawl|shop` set the pause; these pin that the
worker honours it everywhere a run could start or go on, and that the sync from
sources.toml, which rewrites `enabled` on every deploy, never touches it.
"""

from __future__ import annotations

from types import SimpleNamespace

from makhzan_schemas import crawl
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import ListingStatus
from makhzan_schemas.models import IngestionRun, Source
from sqlalchemy import select
from test_crawl_phase1 import _run_until_cycle, _status_of, _woo_adapter
from test_crawl_phase1 import allow_robots, woo  # noqa: F401 — fixtures
from test_pipeline import SRC, StubAdapter, _cursors, _listings
from test_worker_jobs import FakeRedis
from worker import main, pause
from worker.pipeline import CONFIRM_MAX_FAILED_RUNS, run_source
from worker.sources.sync import sync_sources


def _source(source_id: str, **kw) -> Source:
    return Source(
        source_id=source_id,
        adapter="fixture",
        supplier={"slug": source_id, "name": source_id},
        config={},
        **kw,
    )


async def _add(*rows: Source) -> None:
    async with SessionLocal() as session:
        session.add_all(rows)
        await session.commit()


async def _pause_shop(source_id: str, note: str | None = "blocked") -> None:
    async with SessionLocal() as session:
        await pause.pause_source(session, source_id, by="tester", note=note)
        await session.commit()


async def _pause_crawl(paused: bool = True) -> None:
    async with SessionLocal() as session:
        await crawl.set_crawl_pause(session, paused, by="tester", note="maintenance")
        await session.commit()


def _cron(monkeypatch, ids: list[str]) -> None:
    async def no_load():
        return None

    monkeypatch.setattr(main, "load_adapters", no_load)
    monkeypatch.setattr(main, "all_enabled", lambda: [SimpleNamespace(source_id=i) for i in ids])
    monkeypatch.setattr(main, "CRAWL_ENABLED", True)


async def test_the_daily_cron_leaves_a_paused_shop_out(monkeypatch):
    await _add(_source("shop-a"), _source("shop-b"))
    await _pause_shop("shop-b")
    _cron(monkeypatch, ["shop-a", "shop-b"])
    redis = FakeRedis()
    queued = await main.refresh_all({"redis": redis})
    assert {q["source"]: q["status"] for q in queued} == {"shop-a": "queued", "shop-b": "skipped"}
    assert [j.split(":")[1] for j in redis.named("crawl_source")] == ["shop-a"]


async def test_the_crawl_wide_pause_queues_nothing_and_resuming_queues_again(monkeypatch):
    await _add(_source("shop-a"))
    _cron(monkeypatch, ["shop-a"])
    await _pause_crawl(True)
    redis = FakeRedis()
    (skipped,) = await main.refresh_all({"redis": redis})
    assert skipped["status"] == "skipped" and "paused by tester" in skipped["reason"]
    assert redis.jobs == {}
    async with SessionLocal() as session:
        assert await crawl.crawl_enabled_in(session) is False  # what /how-we-crawl reads

    await _pause_crawl(False)
    assert [q["status"] for q in await main.refresh_all({"redis": redis})] == ["queued"]
    async with SessionLocal() as session:
        assert await crawl.crawl_enabled_in(session) is True


async def test_a_daily_job_queued_before_the_pause_skips_the_shop(monkeypatch):
    await _add(_source("shop-a"))
    await _pause_shop("shop-a")
    monkeypatch.setattr(main, "CRAWL_ENABLED", True)
    ran: list[str] = []

    async def run(source_id, adapter, limit=None):
        ran.append(source_id)

    monkeypatch.setattr(main, "_run_source", run)
    monkeypatch.setattr(main, "get", lambda source_id: None)
    summary = await main.crawl_source({"redis": FakeRedis()}, "shop-a")
    assert summary["status"] == "skipped" and "shop paused by tester" in summary["reason"]
    assert ran == []


async def test_the_sync_from_sources_toml_keeps_a_pause():
    """`enabled` is the file's and rewritten on every deploy; the pause is not."""
    await _add(_source("shop-a"))
    await _pause_shop("shop-a", note="403 since Monday")
    changed = _source("shop-a", base_url="https://shop-a.test", enabled=True)
    async with SessionLocal() as session:
        report = await sync_sources(session, [changed])
    assert report["updated"] == ["shop-a"]
    async with SessionLocal() as session:
        row = await session.scalar(select(Source).where(Source.source_id == "shop-a"))
    assert row.base_url == "https://shop-a.test"
    assert row.paused_at is not None
    assert (row.paused_by, row.pause_note) == ("tester", "403 since Monday")


async def test_resuming_clears_the_pause_and_pausing_twice_keeps_the_first():
    await _add(_source("shop-a"))
    await _pause_shop("shop-a", note="first")
    await _pause_shop("shop-a", note="second")
    async with SessionLocal() as session:
        assert (await pause.paused_reason(session, "shop-a")) == "shop paused by tester"
        row = await session.scalar(select(Source).where(Source.source_id == "shop-a"))
        assert row.pause_note == "first"
        await pause.resume_source(session, "shop-a")
        await session.commit()
        assert await pause.paused_reason(session, "shop-a") is None
        assert await pause.paused_sources(session) == set()


class PausedMidRun(StubAdapter):
    """Pauses its own shop, from another session, while page 1 is being read."""

    async def fetch_page(self, partition, page):
        if page == 1:
            await _pause_shop(SRC, note="paused mid-run")
        return await super().fetch_page(partition, page)


async def test_a_full_run_stops_at_the_next_page_and_keeps_its_cursor():
    await _add(_source(SRC))
    adapter = PausedMidRun()
    await run_source(SRC, adapter)
    # Page 1 was already being read: it is kept; page 2 is never asked for.
    assert adapter.fetched == [("", 1)]
    assert sorted(x.external_id for x in await _listings()) == ["a1", "a2"]
    assert await _cursors() == {"": (2, False)}
    async with SessionLocal() as session:
        run = await session.scalar(select(IngestionRun).where(IngestionRun.source == SRC))
    assert "shop paused by tester" in run.stats["stopped"]


async def test_a_run_started_while_paused_sends_nothing():
    await _add(_source(SRC))
    await _pause_crawl(True)
    adapter = StubAdapter()
    await run_source(SRC, adapter)
    assert adapter.fetched == []
    async with SessionLocal() as session:
        run = await session.scalar(select(IngestionRun).where(IngestionRun.source == SRC))
    assert "crawl paused" in run.stats["stopped"]


async def test_a_limit_run_still_works_on_a_paused_shop():
    """The dashboard's "Run now" is how a paused shop is looked at."""
    await _add(_source(SRC))
    await _pause_shop(SRC)
    adapter = StubAdapter()
    await run_source(SRC, adapter, limit=3)
    assert adapter.fetched == [("", 1), ("", 2)]


async def test_the_cli_pauses_and_resumes(capsys):
    await _add(_source("shop-a"))
    assert await pause.run(["shop", "pause", "shop-a", "--note", "why", "--by", "ops"]) == 0
    assert await pause.run(["shop"]) == 0
    assert "PAUSED" in capsys.readouterr().out
    assert await pause.run(["shop", "resume", "shop-a"]) == 0
    assert await pause.run(["shop", "pause", "nope"]) == 1
    assert await pause.run(["crawl", "off", "--by", "ops"]) == 0
    assert "the daily crawl is OFF" in capsys.readouterr().out
    assert await pause.run(["crawl", "on", "--by", "ops"]) == 0
    assert "the daily crawl is on" in capsys.readouterr().out


async def test_make_status_shows_both_pauses(capsys):
    from worker import status

    await _add(_source(SRC))
    await run_source(SRC, StubAdapter(fail_on_page=2))  # an open cycle, cursor at page 2
    await _pause_shop(SRC, note="blocked by its host")
    await _pause_crawl(True)
    async with SessionLocal() as session:
        await status.sweep_progress(session, None)
    out = capsys.readouterr().out
    assert "the whole crawl is paused by tester" in out
    assert "paused by tester" in out and "blocked by its host" in out
    assert "the daily run skips it" in out


async def test_a_pause_holds_a_held_cycle_without_counting_confirmation_attempts(woo):  # noqa: F811
    """A paused run must not reach the archive confirmation: its refusal to ask
    would count as a failed attempt, and after CONFIRM_MAX_FAILED_RUNS the
    candidates archive unconfirmed, on the very shop a person paused."""
    await _add(_source("woo"))
    woo.catalogue = {1: "instock", 2: "instock"}
    await _run_until_cycle()
    del woo.catalogue[2]
    woo.include_status = 500
    for _ in range(5):
        first = await run_source("woo", _woo_adapter())
        if first.stats.get("archive_confirm"):
            break
    assert first.stats["archive_confirm"]["attempt"] == 1  # held after one failed attempt

    await _pause_shop("woo")
    asked = len(woo.included())
    for _ in range(CONFIRM_MAX_FAILED_RUNS + 2):
        paused_run = await run_source("woo", _woo_adapter())
        assert "archive_confirm" not in paused_run.stats
        assert not paused_run.stats.get("archived") and not paused_run.stats.get("cycle")
    assert len(woo.included()) == asked, "nothing asked while paused"
    assert (await _status_of("2")).status == ListingStatus.ACTIVE

    # Resumed: the next failed attempt is the second, not the fifth.
    async with SessionLocal() as session:
        await pause.resume_source(session, "woo")
        await session.commit()
    second = await run_source("woo", _woo_adapter())
    assert second.stats["archive_confirm"]["attempt"] == 2
