"""A run stops early, cleanly, when its own host refuses it or its time is up.

An unreadable robots.txt right after a deploy used to cost a source its whole
day: every partition failed on page 1 with the same error while the loop still
slept the pace between them, and the cycle data was stamped as attempted. Now
the run stops at the first refusal, keeps every cursor, and says why.
"""

from __future__ import annotations

import httpx
import pytest
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import IngestionStatus, SourceType
from makhzan_schemas.models import Source, SourceCursor
from sqlalchemy import select

from worker import http as http_mod
from worker import pipeline
from worker import robots as robots_mod
from worker.pipeline import run_source
from worker.sources.base import Page, RawItem, SourceAdapter, SupplierInfo


class _Shop(SourceAdapter):
    source_id = "halting-shop"
    source_type = SourceType.SCRAPED
    supplier = SupplierInfo(slug="halting-shop", name="Halting Shop")
    polite_delay = 15.0
    base_url = "https://shop.test"

    def partitions(self) -> list[str]:
        return ["a", "b", "c"]

    def cycle_data_parts(self) -> list[str]:
        return ["tree"]

    async def fetch_cycle_part(self, fetcher, part: str) -> object:
        await fetcher.get(part, f"{self.base_url}/tree")
        return {}

    async def fetch_page(self, partition: str, page: int) -> Page:
        async with http_mod.make_client() as client:
            await http_mod.get_json(client, f"{self.base_url}/{partition}/{page}")
        item = RawItem(
            source=self.source_id,
            external_id=f"{partition}{page}",
            title=f"Part {partition}{page}",
            price_text="10 EGP",
            availability_text="In stock",
        )
        return Page([item], has_more=False)


@pytest.fixture
def world(monkeypatch):
    """Every client routed to `handler`; sleeps recorded, not slept."""
    state = {"robots": [503], "sent": [], "sleeps": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["sent"].append(request.url.path)
        if request.url.path == "/robots.txt":
            statuses = state["robots"]
            return httpx.Response(statuses.pop(0) if len(statuses) > 1 else statuses[0])
        return httpx.Response(200, json={})

    real = httpx.AsyncClient
    transport = httpx.MockTransport(handler)

    def client(**kwargs):
        kwargs.setdefault("transport", transport)
        return real(**kwargs)

    async def sleep(seconds):
        state["sleeps"].append(seconds)

    monkeypatch.setattr(httpx, "AsyncClient", client)
    monkeypatch.setattr(http_mod.asyncio, "sleep", sleep)
    monkeypatch.setattr(robots_mod, "ROBOTS", robots_mod.RobotsCache())
    monkeypatch.setattr(http_mod, "_NOT_BEFORE", {})
    return state


async def _seed_source() -> None:
    async with SessionLocal() as session:
        session.add(
            Source(
                source_id=_Shop.source_id,
                adapter="fixture",
                enabled=True,
                supplier={"slug": "halting-shop", "name": "Halting Shop"},
                config={},
            )
        )
        await session.commit()


async def test_an_unreadable_robots_txt_stops_the_run_at_once(world):
    await _seed_source()
    run = await run_source(_Shop.source_id, _Shop())

    # robots.txt asked twice (the retry), then nothing else at all.
    assert world["sent"] == ["/robots.txt", "/robots.txt"]
    assert run.status == IngestionStatus.PARTIAL
    assert run.stats["stopped"].startswith("refused by its host: robots.txt for https://shop.test")
    assert len(run.stats["errors"]) == 1  # the cycle data's; no partition was tried
    assert run.stats["robots"]["https://shop.test"]["state"] == "unavailable"
    assert "pages" not in run.stats.get("requests", {})
    # No idle pauses between partitions that were never going to be read.
    assert all(s < 60 for s in world["sleeps"]) and len(world["sleeps"]) <= 2

    async with SessionLocal() as session:
        cursors = (await session.execute(select(SourceCursor))).scalars().all()
        source = (await session.execute(select(Source))).scalar_one()
    assert cursors == []  # nothing moved
    # Not stamped as attempted: tomorrow's run fetches it again.
    assert "tree" not in (source.cycle_data or {})


async def test_a_refusal_mid_sweep_stops_the_remaining_partitions(world):
    """Partition b's host asks for a longer wait than we wait out: c is not tried."""
    world["robots"] = [200]

    class _BacksOff(_Shop):
        async def fetch_page(self, partition, page):
            if partition == "b":
                http_mod._NOT_BEFORE["https://shop.test"] = http_mod.time.monotonic() + 10**6
            return await super().fetch_page(partition, page)

    run = await run_source(_Shop.source_id, _BacksOff())
    assert "/a/1" in world["sent"]
    assert "/b/1" not in world["sent"] and "/c/1" not in world["sent"]
    assert run.stats["stopped"].startswith("refused by its host")
    assert sum("asked us to wait" in e for e in run.stats["errors"]) == 1
    assert run.stats["requests"]["pages"] == 1  # b was refused before sending


async def test_a_page_refused_before_sending_is_not_counted(world):
    world["robots"] = [200]

    class _Disallowed(_Shop):
        async def fetch_page(self, partition, page):
            raise robots_mod.DisallowedByRobots(f"{self.base_url}/{partition}")

    run = await run_source(_Shop.source_id, _Disallowed())
    assert "pages" not in run.stats["requests"]


async def test_the_run_stops_itself_before_the_job_timeout(world, monkeypatch):
    """However slow the host makes it, the run ends before arq would cancel it."""
    world["robots"] = [200]
    ticks = iter([0.0, 10.0, 10.0, 10.0 + pipeline.JOB_TIMEOUT])

    def clock():
        return next(ticks, 10.0 + pipeline.JOB_TIMEOUT)

    monkeypatch.setattr(pipeline, "_clock", clock)
    run = await run_source(_Shop.source_id, _Shop())
    assert run.stats["stopped"] == "time budget spent; the cursors resume next run"
    assert run.status == IngestionStatus.SUCCESS
    async with SessionLocal() as session:
        cursors = (await session.execute(select(SourceCursor))).scalars().all()
    # Partition a was swept; b and c wait for the next run.
    assert {c.partition_key for c in cursors if c.exhausted} == {"a"}


def test_the_slowdown_alone_cannot_outlast_the_job():
    """The bound, written down: the run's own deadline sits inside the job timeout."""
    assert pipeline.RUN_TIME_SHARE < 1.0
