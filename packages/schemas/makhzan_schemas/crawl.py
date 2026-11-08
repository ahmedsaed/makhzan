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
    """Whether the daily sweep is switched on (`CRAWL_ENABLED`, default on)."""
    return os.getenv("CRAWL_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}


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


def merge_gaps(pacings: Iterable[Mapping]) -> tuple[float | None, int | None]:
    """The shortest gap and the median gap (whole seconds, floored) across runs.

    Only runs that measured gaps contribute; runs from before pacing was
    recorded have nothing to say and are left out rather than guessed. None
    when nothing was measured.
    """
    shortest: float | None = None
    histogram: Counter[int] = Counter()
    for pacing in pacings:
        low = pacing.get("min_gap_s")
        if isinstance(low, (int, float)):
            shortest = low if shortest is None else min(shortest, low)
        for second, n in (pacing.get("gaps") or {}).items():
            try:
                histogram[int(second)] += int(n)
            except (TypeError, ValueError):
                continue
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
