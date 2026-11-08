"""GET /crawler/activity — the public record of how the crawler treats each shop.

Shop owners read this to check us against their own logs, so two things matter
as much as the numbers: nothing is invented (a run that measured no gaps gives
null, not a guess), and nothing internal leaks (errors, status codes, source
ids, resume points).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from factories import make_supplier
from makhzan_schemas import crawl
from makhzan_schemas.enums import IngestionStatus, SourceType
from makhzan_schemas.models import IngestionRun, Source


async def _source(db, source_id: str, slug: str, *, enabled: bool = True) -> Source:
    source = Source(
        source_id=source_id,
        adapter="woocommerce",
        base_url=f"https://{slug}.test",
        enabled=enabled,
        supplier={"slug": slug, "name": slug},
        config={},
    )
    db.add(source)
    await db.commit()
    return source


async def _run(
    db,
    source_id: str,
    *,
    ago: timedelta,
    took: timedelta = timedelta(minutes=30),
    stats: dict | None = None,
    items_seen: int = 10,
    finished: bool = True,
) -> IngestionRun:
    started = datetime.now(UTC) - ago
    run = IngestionRun(
        source=source_id,
        source_type=SourceType.SCRAPED,
        # A run a deploy stopped is closed by the next worker (worker.main.
        # close_interrupted_runs): FAILED, and "finished" when that worker started.
        status=IngestionStatus.SUCCESS if finished else IngestionStatus.FAILED,
        started_at=started,
        finished_at=started + took,
        items_seen=items_seen,
        stats=stats or {},
    )
    db.add(run)
    await db.commit()
    return run


def _paced(*gaps: float) -> dict:
    times = [0.0]
    for gap in gaps:
        times.append(times[-1] + gap)
    return crawl.pacing_stats({"https://shop.test": times})


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


async def _activity(client) -> dict:
    response = await client.get("/crawler/activity")
    assert response.status_code == 200
    return response.json()


async def test_an_active_shop_reports_its_week(client, db):
    await make_supplier(db, slug="shop-a", name="Shop A")
    await _source(db, "src-a", "shop-a")
    await _run(
        db,
        "src-a",
        ago=timedelta(days=1),
        stats={"requests": {"pages": 3}, "pacing": _paced(15.2, 20.0, 16.0)},
    )
    latest = await _run(
        db,
        "src-a",
        ago=timedelta(hours=3),
        stats={"requests": {"pages": 2}, "pacing": _paced(17.5)},
    )
    # Outside the window: not counted, gaps not used.
    await _run(db, "src-a", ago=timedelta(days=9), stats={"pacing": _paced(1.0, 1.0)})

    body = await _activity(client)

    assert body["shops"] == [
        {
            "slug": "shop-a",
            "name": "Shop A",
            "status": "active",
            "last_read_at": body["shops"][0]["last_read_at"],
            "requests_7d": 6,
            "requests_7d_partial": False,
            "min_gap_s": 15.2,
            # Gaps 15.2, 16, 17.5, 20 by whole second: 15, 16, 17, 20; lower median 16.
            "median_gap_s": 16,
        }
    ]
    assert _parse(body["shops"][0]["last_read_at"]) == latest.finished_at
    assert body["totals"] == {
        "shops": 1,
        "shops_active": 1,
        "shops_read_7d": 1,
        "requests_7d": 6,
        "requests_7d_partial": False,
        "min_gap_s": 15.2,
        "median_gap_s": 16,
        "robots_txt_honoured": True,
    }
    assert body["window_days"] == 7


async def test_a_paused_shop_is_paused_and_says_nothing_more(client, db):
    await make_supplier(db, slug="quiet-shop", name="Quiet Shop")
    await _source(db, "src-quiet", "quiet-shop", enabled=False)
    await _run(
        db,
        "src-quiet",
        ago=timedelta(days=20),
        stats={
            "errors": ["p1: Client error '403 Forbidden' for url 'https://quiet-shop.test/x'"],
            "requests": {"pages": 1},
            "pacing": _paced(),
        },
    )

    body = await _activity(client)
    (shop,) = body["shops"]
    assert shop["status"] == "paused"
    assert shop["requests_7d"] == 0
    assert body["totals"]["shops_active"] == 0
    assert body["totals"]["shops_read_7d"] == 0
    # The run's error never leaves the database, nor does the source's id.
    text = json.dumps(body).lower()
    for word in ("403", "forbidden", "error", "blocked", "src-quiet", "quiet-shop.test"):
        assert word not in text, word


async def test_a_source_with_no_runs_has_nothing_to_report_yet(client, db):
    await make_supplier(db, slug="new-shop", name="New Shop")
    await _source(db, "src-new", "new-shop")

    (shop,) = (await _activity(client))["shops"]
    assert shop == {
        "slug": "new-shop",
        "name": "New Shop",
        "status": "active",
        "last_read_at": None,
        "requests_7d": 0,
        "requests_7d_partial": False,
        "min_gap_s": None,
        "median_gap_s": None,
    }


async def test_runs_from_before_pacing_count_requests_but_give_no_gaps(client, db):
    await make_supplier(db, slug="old-shop", name="Old Shop")
    await _source(db, "src-old", "old-shop")
    run = await _run(db, "src-old", ago=timedelta(days=2), stats={"requests": {"pages": 40}})

    (shop,) = (await _activity(client))["shops"]
    assert shop["requests_7d"] == 40
    assert shop["requests_7d_partial"] is False
    assert shop["min_gap_s"] is None and shop["median_gap_s"] is None
    assert _parse(shop["last_read_at"]) == run.finished_at


async def test_a_run_that_never_wrote_its_stats_makes_the_count_a_floor(client, db):
    """Stopped mid-run by a deploy: it read the site, but how much is unknown.
    The count says "at least", and the last read is when that run started."""
    await make_supplier(db, slug="shop-b", name="Shop B")
    await _source(db, "src-b", "shop-b")
    await _run(db, "src-b", ago=timedelta(days=2), stats={"pacing": _paced(15, 15)})
    stopped = await _run(db, "src-b", ago=timedelta(hours=5), finished=False)

    (shop,) = (await _activity(client))["shops"]
    assert shop["requests_7d"] == 3
    assert shop["requests_7d_partial"] is True
    assert _parse(shop["last_read_at"]) == stopped.started_at


async def test_a_completed_run_from_before_any_counting_still_read_the_site(client, db):
    await make_supplier(db, slug="shop-e", name="Shop E")
    await _source(db, "src-e", "shop-e")
    run = await _run(db, "src-e", ago=timedelta(days=1), stats={})

    body = await _activity(client)
    (shop,) = body["shops"]
    assert _parse(shop["last_read_at"]) == run.finished_at
    assert (shop["requests_7d"], shop["requests_7d_partial"]) == (0, True)
    # Read this week, even though how much is unknown.
    assert body["totals"]["shops_read_7d"] == 1


async def test_shops_read_this_week_follow_last_read_not_the_request_count(client, db):
    """Three shops read two days ago by runs that never counted their requests
    are three shops read this week, as the table beside the total says."""
    for slug in ("read-1", "read-2", "read-3"):
        await make_supplier(db, slug=slug, name=slug)
        await _source(db, f"src-{slug}", slug)
        await _run(db, f"src-{slug}", ago=timedelta(days=2), stats={})
    await make_supplier(db, slug="read-long-ago", name="read-long-ago")
    await _source(db, "src-long-ago", "read-long-ago")
    await _run(db, "src-long-ago", ago=timedelta(days=13), stats={"pacing": _paced(15)})

    totals = (await _activity(client))["totals"]
    assert (totals["shops_read_7d"], totals["shops"]) == (3, 4)
    assert totals["requests_7d"] == 0 and totals["requests_7d_partial"] is True


async def test_a_run_that_sent_nothing_is_not_a_read(client, db):
    await make_supplier(db, slug="shop-c", name="Shop C")
    await _source(db, "src-c", "shop-c")
    read = await _run(db, "src-c", ago=timedelta(days=3), stats={"pacing": _paced(15)})
    await _run(db, "src-c", ago=timedelta(hours=1), stats={"pacing": {"requests": 0}})

    (shop,) = (await _activity(client))["shops"]
    assert _parse(shop["last_read_at"]) == read.finished_at
    assert shop["requests_7d"] == 2


async def test_a_shop_read_through_two_sources_is_one_row(client, db):
    await make_supplier(db, slug="shop-d", name="Shop D")
    await _source(db, "src-d1", "shop-d", enabled=False)
    await _source(db, "src-d2", "shop-d")
    await _run(db, "src-d1", ago=timedelta(days=1), stats={"pacing": _paced(30)})
    await _run(db, "src-d2", ago=timedelta(days=1), stats={"pacing": _paced(15, 15)})

    (shop,) = (await _activity(client))["shops"]
    assert shop["status"] == "active"
    assert shop["requests_7d"] == 5
    assert shop["min_gap_s"] == 15


async def test_only_shops_with_a_source_are_listed(client, db):
    """A supplier no source reads (or a source whose shop has no row yet) has
    no crawler activity to show."""
    await make_supplier(db, slug="listed-only", name="Listed Only")
    await _source(db, "src-orphan", "never-created")
    assert (await _activity(client))["shops"] == []


async def test_shops_are_listed_by_name(client, db):
    for slug, name in (("zed", "Zed Parts"), ("alpha", "alpha tools"), ("mid", "Mid Shop")):
        await make_supplier(db, slug=slug, name=name)
        await _source(db, f"src-{slug}", slug)
    names = [s["name"] for s in (await _activity(client))["shops"]]
    assert names == ["alpha tools", "Mid Shop", "Zed Parts"]


async def test_the_next_run_follows_the_refresh_hour(client, db, monkeypatch):
    monkeypatch.setattr(crawl, "REFRESH_HOUR", 3)
    schedule = (await _activity(client))["schedule"]
    assert schedule["refresh_hour_utc"] == 3
    next_run = _parse(schedule["next_run_at"])
    now = datetime.now(UTC)
    assert next_run.hour == 3 and next_run.minute == 0
    assert timedelta(0) < next_run - now <= timedelta(days=1)


@pytest.mark.parametrize("value", ["false", "off", "0"])
async def test_no_next_run_while_the_sweep_is_switched_off(client, monkeypatch, value):
    monkeypatch.setenv("CRAWL_ENABLED", value)
    assert (await _activity(client))["schedule"]["next_run_at"] is None
