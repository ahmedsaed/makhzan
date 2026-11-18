"""How the crawler paces itself, as recorded and as published.

One definition shared by the worker, which writes `stats.pacing` on every run,
and the API, which reads it back for the public "Crawler activity" view on
/how-we-crawl. Keeping both sides here means the format cannot drift between
the code that measures and the code that reports.

`stats.pacing` on an `IngestionRun`:

    {
      "requests": 412,            # requests actually sent to the shop, retries included
      "robots": 2,                # of which robots.txt fetches
      "min_gap_s": 15.0,          # between consecutive requests to one host
      "median_gap_s": 15.2,
      "max_gap_s": 61.4,
      "gaps": {"15": 380, ...},   # every gap, by whole second (floored)
      "by_host": {"https://shop.test": {"requests": ..., "min_gap_s": ..., ...}},
    }

Gaps are only ever measured between two requests to the same host in the same
run: the pause between one day's run and the next is not a pacing decision. A
run with one request has no gap, and its gap fields are null.

The histogram is what lets the API give a median over a week of runs without
storing every timestamp: medians do not add up, counts do. Floored to the
second, so a median read from it never claims more patience than was shown.
"""

from __future__ import annotations

import os
import statistics
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, time, timedelta, timezone

#: Hour of day (UTC) the daily refresh starts. Read by the worker's cron and by
#: the API, which publishes when the next run starts.
REFRESH_HOUR = int(os.getenv("REFRESH_HOUR", "3"))


def crawl_enabled() -> bool:
    """Whether the daily sweep is switched on (`CRAWL_ENABLED`, default on).

    The worker's own reading, from its environment. Anything else asking
    whether the worker crawls reads `crawl_enabled_in` instead.
    """
    return os.getenv("CRAWL_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


#: `WorkerState` key the worker states its crawl flag under.
CRAWL_STATE_KEY = "crawl"


async def record_crawl_enabled(session, enabled: bool) -> None:
    """The worker, at startup: say whether it will run the daily sweep. Commits."""
    from sqlalchemy import func
    from sqlalchemy.dialects.postgresql import insert

    from makhzan_schemas.models import WorkerState

    value = {"enabled": bool(enabled)}
    await session.execute(
        insert(WorkerState)
        .values(key=CRAWL_STATE_KEY, value=value)
        .on_conflict_do_update(
            index_elements=[WorkerState.key],
            set_={"value": value, "updated_at": func.now()},
        )
    )
    await session.commit()


async def worker_crawl_enabled(session) -> bool:
    """`CRAWL_ENABLED` as the worker last stated it at startup.

    The API's own `CRAWL_ENABLED` is whatever it was when the API was last
    created; the worker's word is in the database. Before any worker has said
    (a fresh database), the environment is the best guess there is.
    """
    from makhzan_schemas.models import WorkerState

    state = await session.get(WorkerState, CRAWL_STATE_KEY)
    if state is None or not isinstance(state.value, dict) or "enabled" not in state.value:
        return crawl_enabled()
    return bool(state.value["enabled"])


async def crawl_enabled_in(session) -> bool:
    """Whether the worker runs the daily sweep: its `CRAWL_ENABLED`, and no pause.

    Two switches, both off means no sweep: the environment the worker was
    created with (`worker_crawl_enabled`), and the pause a person sets in the
    database (`crawl_pause`: the admin dashboard, `./makhzan crawl off`),
    which the worker reads each time it would start a run.
    """
    if not await worker_crawl_enabled(session):
        return False
    return await crawl_pause(session) is None


#: `WorkerState` key of the crawl-wide pause a person sets.
PAUSE_STATE_KEY = "crawl_pause"


async def crawl_pause(session) -> dict | None:
    """The crawl-wide pause, if one is set: `{"at": iso, "by": ..., "note": ...}`.

    Set by the admin dashboard and `./makhzan crawl off`, cleared by their
    "resume"/`on`. Unlike `CRAWL_ENABLED` it needs no container recreated:
    `refresh_all` and `crawl_source` read it each time, and a full run in
    flight reads it before every page and stops there, its cursors kept.
    """
    from makhzan_schemas.models import WorkerState

    state = await session.get(WorkerState, PAUSE_STATE_KEY, populate_existing=True)
    if state is None or not isinstance(state.value, dict) or not state.value.get("paused"):
        return None
    return state.value


async def crawl_resumed_at(session):
    """When the crawl-wide pause was last lifted, if ever (a datetime, or None)."""
    from datetime import datetime

    from makhzan_schemas.models import WorkerState

    state = await session.get(WorkerState, PAUSE_STATE_KEY, populate_existing=True)
    stamp = (state.value or {}).get("resumed_at") if state is not None else None
    try:
        return datetime.fromisoformat(stamp) if stamp else None
    except (TypeError, ValueError):
        return None


async def set_crawl_pause(session, paused: bool, *, by: str, note: str | None = None) -> dict:
    """Pause or resume the whole crawl (flushed, not committed). Returns the stored value."""
    from datetime import datetime, timezone

    from sqlalchemy import func
    from sqlalchemy.dialects.postgresql import insert

    from makhzan_schemas.models import WorkerState

    now = datetime.now(timezone.utc).isoformat()
    before = await session.get(WorkerState, PAUSE_STATE_KEY, populate_existing=True)
    earlier = before.value if before is not None and isinstance(before.value, dict) else {}
    value = {
        "paused": bool(paused),
        "at": now,
        "by": by,
        "note": (note or "").strip() or None,
        # When it was last lifted: the archive confirmation's hold window runs
        # from here, so a long pause does not make the next run overdue.
        "resumed_at": now if (not paused and earlier.get("paused")) else earlier.get("resumed_at"),
    }
    await session.execute(
        insert(WorkerState)
        .values(key=PAUSE_STATE_KEY, value=value)
        .on_conflict_do_update(
            index_elements=[WorkerState.key],
            set_={"value": value, "updated_at": func.now()},
        )
    )
    await session.flush()
    return value


def next_refresh(now: datetime, hour: int = REFRESH_HOUR) -> datetime:
    """When the next daily run starts: today at `hour`:00 UTC, or tomorrow if that has passed."""
    now = now.astimezone(timezone.utc)
    start = datetime.combine(now.date(), time(hour=hour), tzinfo=timezone.utc)
    return start if start > now else start + timedelta(days=1)


def _round(seconds: float) -> float:
    return round(seconds, 2)


def summarize_gaps(requests: int, gaps: list[float]) -> dict:
    """`{requests, min_gap_s, median_gap_s, max_gap_s, gaps}` for one host or one run."""
    if not gaps:
        return {"requests": requests, "min_gap_s": None, "median_gap_s": None, "max_gap_s": None}
    histogram = Counter(str(int(gap)) for gap in gaps)
    return {
        "requests": requests,
        "min_gap_s": _round(min(gaps)),
        "median_gap_s": _round(statistics.median(gaps)),
        "max_gap_s": _round(max(gaps)),
        "gaps": dict(sorted(histogram.items(), key=lambda kv: int(kv[0]))),
    }


def pacing_stats(
    times_by_host: Mapping[str, list[float]], robots: Mapping[str, int] | None = None
) -> dict:
    """A run's `stats.pacing` from when each request went out, by host (monotonic seconds).

    `robots` counts the robots.txt fetches among them, by host. They are
    requests the shop sees, so they are in `requests` and in the gaps.
    """
    by_host: dict[str, dict] = {}
    every_gap: list[float] = []
    for host, times in sorted(times_by_host.items()):
        ordered = sorted(times)
        gaps = [later - earlier for earlier, later in zip(ordered, ordered[1:])]
        every_gap.extend(gaps)
        by_host[host] = summarize_gaps(len(ordered), gaps)
        by_host[host].pop("gaps", None)  # the run's histogram covers every host
    total = sum(entry["requests"] for entry in by_host.values())
    summary = summarize_gaps(total, every_gap)
    fetched_robots = sum((robots or {}).values())
    if fetched_robots:
        summary["robots"] = fetched_robots
    return {**summary, "by_host": by_host}


def merge_histogram(pacings: Iterable[Mapping]) -> Counter[int]:
    """Every run's `gaps` histogram added up: whole seconds -> how many gaps."""
    histogram: Counter[int] = Counter()
    for pacing in pacings:
        for second, n in (pacing.get("gaps") or {}).items():
            try:
                histogram[int(second)] += int(n)
            except (TypeError, ValueError):
                continue
    return histogram


def merge_gaps(pacings: Iterable[Mapping]) -> tuple[float | None, int | None]:
    """The shortest gap and the median gap (whole seconds, floored) across runs.

    Only runs that measured gaps contribute; runs from before pacing was
    recorded have nothing to say and are left out rather than guessed. None
    when nothing was measured.
    """
    pacings = list(pacings)
    shortest: float | None = None
    for pacing in pacings:
        low = pacing.get("min_gap_s")
        if isinstance(low, (int, float)):
            shortest = low if shortest is None else min(shortest, low)
    histogram = merge_histogram(pacings)
    total = histogram.total()
    if not total:
        return shortest, None
    # The lower median: of an even count, the smaller middle value.
    middle = (total + 1) // 2
    seen = 0
    for second in sorted(histogram):
        seen += histogram[second]
        if seen >= middle:
            return shortest, second
    return shortest, None  # unreachable


#: Where the published gap histogram's buckets start, in whole seconds. The
#: first holds anything under our 15 s default, so a gap shorter than we
#: promise shows up rather than being folded into the 15 s bucket; the last
#: is open-ended. Fixed, so the page's rows do not move from week to week.
GAP_BUCKETS: tuple[int, ...] = (0, 15, 16, 17, 18, 20, 30, 60)


def bucket_gaps(histogram: Mapping[int, int]) -> list[dict] | None:
    """`histogram` (whole seconds -> count) as the published buckets.

    `[{"min_s": 15, "max_s": 15, "count": 380}, ..., {"min_s": 60, "max_s": None, ...}]`,
    every bucket present, empty ones at 0. None when nothing was measured.
    """
    if not sum(histogram.values()):
        return None
    buckets = []
    for i, low in enumerate(GAP_BUCKETS):
        high = GAP_BUCKETS[i + 1] - 1 if i + 1 < len(GAP_BUCKETS) else None
        count = sum(
            n
            for second, n in histogram.items()
            if second >= low and (high is None or second <= high)
        )
        buckets.append({"min_s": low, "max_s": high, "count": count})
    return buckets


def public_identity(identity: object) -> dict | None:
    """What may be published of a run's `stats.identity`: its name and whether it signed.

    The signing key's id stays on the row (`make status` shows it); the page
    says only "makhzanbot, signed" or "browser". None for a run from before
    the identity was recorded, or anything unrecognised.
    """
    if not isinstance(identity, Mapping):
        return None
    name = identity.get("name")
    if name not in ("makhzanbot", "browser"):
        return None
    return {"name": name, "signed": name == "makhzanbot" and identity.get("signed") is True}
