"""GET /crawler/activity — the public record of how the crawler treats each shop.

Shop owners read this to check us against their own logs, so two things matter
as much as the numbers: nothing is invented (a run that measured no gaps gives
null, not a guess), and nothing internal leaks (errors, status codes, source
ids, resume points).
"""

from __future__ import annotations

import json
import re
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
            "requests_by_day": body["shops"][0]["requests_by_day"],
            "identity": None,
            "last_cycle_days": None,
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
        "gap_histogram": body["totals"]["gap_histogram"],
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
    for word in ("forbidden", "error", "blocked", "src-quiet", "quiet-shop.test"):
        assert word not in text, word
    # The status code as a whole token: as a bare substring, "403" also turned up
    # inside timestamps ("...14:03:00" after a "4"), which failed this test now
    # and then for nothing.
    assert not re.search(r"(?<!\d)403(?!\d)", text), text


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
        "requests_by_day": [
            {"date": (datetime.now(UTC).date() - timedelta(days=back)).isoformat(), "requests": 0}
            for back in range(6, -1, -1)
        ],
        "identity": None,
        "last_cycle_days": None,
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


async def test_every_shop_reads_paused_while_the_whole_crawl_is_off(client, db, monkeypatch):
    """CRAWL_ENABLED off stops every source; the page must not call them active."""
    await make_supplier(db, slug="shop-a", name="Shop A")
    await _source(db, "shop-a", "shop-a", enabled=True)
    monkeypatch.setenv("CRAWL_ENABLED", "false")
    body = await _activity(client)
    assert [shop["status"] for shop in body["shops"]] == ["paused"]
    assert body["totals"]["shops_active"] == 0


async def test_the_worker_saying_off_wins_over_the_apis_own_environment(client, db, monkeypatch):
    """`./makhzan crawl off` recreates the worker alone, so the API's own
    CRAWL_ENABLED still says on. The worker's word, stated at its startup, is
    what the page reports."""
    await make_supplier(db, slug="shop-a", name="Shop A")
    await _source(db, "shop-a", "shop-a", enabled=True)
    monkeypatch.setenv("CRAWL_ENABLED", "true")
    await crawl.record_crawl_enabled(db, False)

    body = await _activity(client)
    assert body["schedule"]["next_run_at"] is None
    assert [shop["status"] for shop in body["shops"]] == ["paused"]


async def test_the_worker_saying_on_wins_too(client, db, monkeypatch):
    monkeypatch.setenv("CRAWL_ENABLED", "false")
    await crawl.record_crawl_enabled(db, False)
    await crawl.record_crawl_enabled(db, True)  # `./makhzan crawl on`: stated again
    assert (await _activity(client))["schedule"]["next_run_at"] is not None


# --- requests by day, identity, last full pass, the gap histogram ----------------


def _day(back: int) -> str:
    return (datetime.now(UTC).date() - timedelta(days=back)).isoformat()


async def _run_on(db, source_id: str, back: int, **kwargs) -> IngestionRun:
    """A run that started `back` days ago (UTC), early in that day."""
    today = datetime.now(UTC).replace(hour=0, minute=30, second=0, microsecond=0)
    started = today - timedelta(days=back)
    return await _run(db, source_id, ago=datetime.now(UTC) - started, **kwargs)


async def test_requests_by_day_cover_the_last_seven_days_oldest_first(client, db):
    await make_supplier(db, slug="shop-a", name="Shop A")
    await _source(db, "src-a", "shop-a")
    await _run_on(db, "src-a", 6, stats={"pacing": _paced(15, 15)})  # 3 requests
    await _run_on(db, "src-a", 2, stats={"requests": {"pages": 40, "details": 2}})
    await _run_on(db, "src-a", 2, stats={"pacing": {"requests": 8}})
    # A day with a run that never said how many it sent is unknown, not zero
    # and not a floor, even beside a run that did.
    await _run_on(db, "src-a", 1, stats={"pacing": {"requests": 5}})
    await _run_on(db, "src-a", 1, stats={}, finished=False)
    # Before the window: not a day of it.
    await _run_on(db, "src-a", 8, stats={"pacing": {"requests": 99}})

    (shop,) = (await _activity(client))["shops"]
    assert shop["requests_by_day"] == [
        {"date": _day(6), "requests": 3},
        {"date": _day(5), "requests": 0},
        {"date": _day(4), "requests": 0},
        {"date": _day(3), "requests": 0},
        {"date": _day(2), "requests": 50},
        {"date": _day(1), "requests": None},
        {"date": _day(0), "requests": 0},
    ]


async def test_a_shop_read_through_two_sources_adds_its_days_up(client, db):
    await make_supplier(db, slug="shop-d", name="Shop D")
    await _source(db, "src-d1", "shop-d")
    await _source(db, "src-d2", "shop-d")
    await _run_on(db, "src-d1", 0, stats={"pacing": {"requests": 4}})
    await _run_on(db, "src-d2", 0, stats={"pacing": {"requests": 6}})
    (shop,) = (await _activity(client))["shops"]
    assert shop["requests_by_day"][-1] == {"date": _day(0), "requests": 10}


async def test_identity_is_the_latest_runs_name_and_signature_only(client, db):
    await make_supplier(db, slug="moved", name="Moved")
    await _source(db, "src-moved", "moved")
    await _run(
        db,
        "src-moved",
        ago=timedelta(days=3),
        stats={"identity": {"name": "browser", "signed": False}},
    )
    await _run(
        db,
        "src-moved",
        ago=timedelta(hours=4),
        stats={"identity": {"name": "makhzanbot", "signed": True, "keyid": "SECRET-THUMBPRINT"}},
    )
    # A later run that recorded no identity (from before it was recorded) says nothing.
    await _run(db, "src-moved", ago=timedelta(hours=1), stats={"pacing": {"requests": 1}})
    await make_supplier(db, slug="not-moved", name="Not Moved")
    await _source(db, "src-not-moved", "not-moved")
    await _run(
        db,
        "src-not-moved",
        ago=timedelta(hours=2),
        stats={"identity": {"name": "browser", "signed": False}},
    )
    await make_supplier(db, slug="unsigned", name="Unsigned")
    await _source(db, "src-unsigned", "unsigned")
    await _run(
        db,
        "src-unsigned",
        ago=timedelta(hours=2),
        stats={"identity": {"name": "makhzanbot", "signed": False}},
    )

    body = await _activity(client)
    by_slug = {shop["slug"]: shop for shop in body["shops"]}
    assert by_slug["moved"]["identity"] == {"name": "makhzanbot", "signed": True}
    assert by_slug["not-moved"]["identity"] == {"name": "browser", "signed": False}
    assert by_slug["unsigned"]["identity"] == {"name": "makhzanbot", "signed": False}
    assert "SECRET-THUMBPRINT" not in json.dumps(body)
    assert "keyid" not in json.dumps(body)


async def test_last_full_pass_is_the_latest_completed_cycle_in_days(client, db):
    await make_supplier(db, slug="shop-a", name="Shop A")
    await _source(db, "src-a", "shop-a")
    cycle = {
        # A year no timestamp in the body can carry, so its absence means something.
        "cycle_started_at": "1999-10-01T03:00:00+00:00",
        "cycle_completed_at": "1999-10-08T03:00:00+00:00",
        "cycle_partitions": 170,
        "cycle_pages": 497,
    }
    await _run(
        db, "src-a", ago=timedelta(days=20), stats={"cycle": {**cycle, "cycle_seconds": 9 * 86400}}
    )
    await _run(
        db, "src-a", ago=timedelta(days=2), stats={"cycle": {**cycle, "cycle_seconds": 561600}}
    )
    await _run(db, "src-a", ago=timedelta(hours=2), stats={"pacing": {"requests": 3}})

    body = await _activity(client)
    (shop,) = body["shops"]
    assert shop["last_cycle_days"] == 6.5
    # Nothing else of the cycle: not its partitions, pages or dates.
    text = json.dumps(body)
    for word in ("cycle_pages", "cycle_partitions", "cycle_started", "cycle_completed"):
        assert word not in text, word
    # Numbers as whole tokens: as bare substrings they turn up inside
    # microsecond timestamps now and then.
    for number in ("497", "170", "1999"):
        assert not re.search(rf"(?<!\d){number}(?!\d)", text), number


async def test_the_week_is_the_seven_days_the_series_shows(client, db):
    """A run late on the eighth day back is inside now-minus-7-days for part of
    the day, but no day of the series shows it: it is not in the week's total,
    nor are its gaps."""
    await make_supplier(db, slug="shop-a", name="Shop A")
    await _source(db, "src-a", "shop-a")
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    eighth_day = midnight - timedelta(days=6) - timedelta(minutes=30)
    await _run(
        db,
        "src-a",
        ago=datetime.now(UTC) - eighth_day,
        stats={"pacing": _paced(3.0, 3.0)},
    )
    first_day = midnight - timedelta(days=6) + timedelta(minutes=30)
    await _run(db, "src-a", ago=datetime.now(UTC) - first_day, stats={"pacing": _paced(15.0, 16.0)})

    body = await _activity(client)
    (shop,) = body["shops"]
    assert shop["requests_7d"] == 3
    assert sum(d["requests"] for d in shop["requests_by_day"]) == 3
    assert shop["requests_by_day"][0] == {"date": _day(6), "requests": 3}
    assert shop["min_gap_s"] == 15.0
    assert body["totals"]["requests_7d"] == 3


async def test_the_gap_histogram_merges_every_shops_gaps_into_fixed_buckets(client, db):
    for slug, gaps in (("shop-a", (15.2, 15.9, 16.4, 21.0)), ("shop-b", (15.0, 75.0, 12.5))):
        await make_supplier(db, slug=slug, name=slug)
        await _source(db, f"src-{slug}", slug)
        await _run(db, f"src-{slug}", ago=timedelta(days=1), stats={"pacing": _paced(*gaps)})
    # Outside the window: left out.
    await _run(db, "src-shop-a", ago=timedelta(days=10), stats={"pacing": _paced(40, 40)})

    histogram = (await _activity(client))["totals"]["gap_histogram"]
    assert histogram == [
        {"min_s": 0, "max_s": 14, "count": 1},
        {"min_s": 15, "max_s": 15, "count": 3},
        {"min_s": 16, "max_s": 16, "count": 1},
        {"min_s": 17, "max_s": 17, "count": 0},
        {"min_s": 18, "max_s": 19, "count": 0},
        {"min_s": 20, "max_s": 29, "count": 1},
        {"min_s": 30, "max_s": 59, "count": 0},
        {"min_s": 60, "max_s": None, "count": 1},
    ]


async def test_no_histogram_when_no_gap_was_measured(client, db):
    await make_supplier(db, slug="old-shop", name="Old Shop")
    await _source(db, "src-old", "old-shop")
    await _run(db, "src-old", ago=timedelta(days=2), stats={"requests": {"pages": 40}})
    assert (await _activity(client))["totals"]["gap_histogram"] is None


async def test_the_new_figures_leak_nothing_private(client, db):
    """A run carrying everything the worker records: only the public figures leave."""
    await make_supplier(db, slug="busy", name="Busy Shop")
    await _source(db, "src-busy", "busy", enabled=False)
    await _run(
        db,
        "src-busy",
        ago=timedelta(hours=6),
        stats={
            "errors": ["p3: Server error '503 Service Unavailable' for url 'https://busy.test/p3'"],
            "stopped": "robots.txt unavailable",
            "robots": {"https://busy.test": {"state": "stale copy"}},
            "identity": {"name": "makhzanbot", "signed": True, "keyid": "kid-123"},
            "budget": {"pages": 40, "target_cycle_days": 7},
            "cycle": {"cycle_seconds": 86400, "cycle_partitions": 9, "cycle_pages": 77},
            "requests": {"pages": 12},
            "pacing": _paced(15, 15, 15),
            # Measurements for tuning the crawl, never for the shop's page.
            "validators": {
                "https://busy.test": {
                    "responses": 12,
                    "etag": 12,
                    "etag_weak": 12,
                    "last_modified": 3,
                }
            },
            "categories": {"set": 1, "moved": 2, "cleared": 0},
        },
    )
    body = await _activity(client)
    (shop,) = body["shops"]
    assert shop["status"] == "paused"
    assert set(shop) == {
        "slug",
        "name",
        "status",
        "last_read_at",
        "requests_7d",
        "requests_7d_partial",
        "min_gap_s",
        "median_gap_s",
        "requests_by_day",
        "identity",
        "last_cycle_days",
    }
    text = json.dumps(body).lower()
    for word in (
        "error",
        "unavailable",
        "stopped",
        "robots.txt unavailable",
        "stale copy",
        "kid-123",
        "keyid",
        "budget",
        "target_cycle",
        "cycle_pages",
        "src-busy",
        "busy.test",
        "validators",
        "etag",
        "last_modified",
        "categories",
        "moved",
    ):
        assert word not in text, word
    assert not re.search(r"(?<!\d)503(?!\d)", text), text
