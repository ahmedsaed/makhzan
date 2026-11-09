"""GET /crawler/activity — what makhzan's crawler did on each shop's site, for the shop to see.

Published on /how-we-crawl and as one line on each shop's page, so that an owner
can check what we say against their own server logs: when we last read their
site, how many requests we sent this week, and how far apart they were.

What this deliberately does NOT say, ever: errors, HTTP status codes, how often
a shop refused us, resume points, crosswalk drift, the review queue, internal
ids (source ids included) or anything about our servers. A paused shop is
"paused", with no reason. That is a decision, not an oversight to be "fixed"
by adding detail. A shop removed at its request is retired
(worker/sources/retire.py), which deletes its source and its runs, so it
simply stops appearing here: there is no "removed" state to report.

Everything comes from `ingestion_runs`: when each run started and finished,
`stats.requests` and `stats.pacing` (makhzan_schemas.crawl). Runs from before
pacing was recorded have no gaps, and the gaps are then null — never guessed.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app.deps import get_session
from fastapi import APIRouter, Depends
from makhzan_schemas import crawl
from makhzan_schemas.enums import IngestionStatus
from makhzan_schemas.models import IngestionRun, Source, Supplier
from sqlalchemy import Integer, and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(tags=["crawler"])

#: The window the request counts and gaps cover.
WINDOW = timedelta(days=7)

_PACING = IngestionRun.stats["pacing"]
_REQUESTS = IngestionRun.stats["requests"]


def _run_requests(pacing: dict | None, requests: dict | None) -> int | None:
    """How many requests a run sent, or None when it never said.

    `stats.pacing.requests` is what was actually sent. Runs from before it was
    recorded carry `stats.requests` (by purpose) instead. A run with neither —
    older still, or stopped before it could write its stats — is unknown.
    """
    if isinstance(pacing, dict) and isinstance(pacing.get("requests"), int):
        return pacing["requests"]
    if isinstance(requests, dict):
        return sum(v for v in requests.values() if isinstance(v, int))
    return None


def _last_read_query():
    """Per source: the last time a run read anything from the site.

    A run that completed finished reading when it finished. One that did not
    (stopped by a deploy, or still going) is placed at its start: the latest
    moment we can vouch for. Its `finished_at`, if any, is when the next worker
    noticed it had stopped, not when it last read.
    """
    completed = IngestionRun.status.in_([IngestionStatus.SUCCESS, IngestionStatus.PARTIAL])
    sent = _PACING["requests"].astext.cast(Integer)
    read_something = case(
        (IngestionRun.stats.has_key("pacing"), sent > 0),
        (IngestionRun.stats.has_key("requests"), True),
        else_=IngestionRun.items_seen > 0,
    )
    when = case(
        (and_(completed, IngestionRun.finished_at.is_not(None)), IngestionRun.finished_at),
        else_=IngestionRun.started_at,
    )
    return (
        select(IngestionRun.source, func.max(when))
        .where(read_something)
        .group_by(IngestionRun.source)
    )


@router.get("/crawler/activity")
async def crawler_activity(session: AsyncSession = Depends(get_session)) -> dict:
    """Per shop we crawl: status, last read, requests and gaps over the last 7 days."""
    now = datetime.now(timezone.utc)
    since = now - WINDOW

    sources = (await session.execute(select(Source))).scalars().all()
    slugs = {s.supplier.get("slug") for s in sources if isinstance(s.supplier, dict)}
    suppliers = {
        s.slug: s
        for s in (
            await session.execute(select(Supplier).where(Supplier.slug.in_(slugs - {None})))
        ).scalars()
    }

    last_read = dict((await session.execute(_last_read_query())).all())
    recent = (
        await session.execute(
            select(IngestionRun.source, _PACING, _REQUESTS).where(IngestionRun.started_at >= since)
        )
    ).all()
    runs: dict[str, list[tuple[dict | None, dict | None]]] = defaultdict(list)
    for source, pacing, requests in recent:
        runs[source].append((pacing, requests))

    # A shop may be read through more than one source; it is one row.
    by_shop: dict[str, list[Source]] = defaultdict(list)
    for source in sources:
        slug = source.supplier.get("slug") if isinstance(source.supplier, dict) else None
        if slug in suppliers:
            by_shop[slug].append(source)

    # What the worker said at startup: the API's own environment is stale
    # after `./makhzan crawl off`, which recreates only the worker.
    crawling = await crawl.crawl_enabled_in(session)
    shops = []
    every_pacing: list[dict] = []
    for slug, its_sources in by_shop.items():
        supplier = suppliers[slug]
        ids = [s.source_id for s in its_sources]
        its_runs = [run for source_id in ids for run in runs.get(source_id, [])]
        counts = [_run_requests(pacing, requests) for pacing, requests in its_runs]
        pacings = [pacing for pacing, _ in its_runs if isinstance(pacing, dict)]
        every_pacing.extend(pacings)
        min_gap, median_gap = crawl.merge_gaps(pacings)
        reads = [last_read[i] for i in ids if last_read.get(i) is not None]
        shops.append(
            {
                "slug": supplier.slug,
                "name": supplier.name,
                # Paused when the shop's sources are switched off, and for every
                # shop while the whole crawl is (CRAWL_ENABLED off).
                "status": (
                    "active" if crawling and any(s.enabled for s in its_sources) else "paused"
                ),
                "last_read_at": max(reads) if reads else None,
                "requests_7d": sum(n for n in counts if n is not None),
                # Some run in the window did not record its requests: the count
                # is a floor, and says so rather than passing for the total.
                "requests_7d_partial": any(n is None for n in counts),
                "min_gap_s": min_gap,
                "median_gap_s": median_gap,
            }
        )
    shops.sort(key=lambda s: (s["name"].casefold(), s["slug"]))

    min_gap, median_gap = crawl.merge_gaps(every_pacing)
    return {
        "generated_at": now,
        "window_days": WINDOW.days,
        "shops": shops,
        "totals": {
            "shops": len(shops),
            "shops_active": sum(1 for s in shops if s["status"] == "active"),
            # Read at all this week, whether or not those runs counted their requests.
            "shops_read_7d": sum(
                1 for s in shops if s["last_read_at"] is not None and s["last_read_at"] >= since
            ),
            "requests_7d": sum(s["requests_7d"] for s in shops),
            "requests_7d_partial": any(s["requests_7d_partial"] for s in shops),
            "min_gap_s": min_gap,
            "median_gap_s": median_gap,
            # Not measured: every request checks robots.txt first (worker/robots.py),
            # and one it disallows is never sent.
            "robots_txt_honoured": True,
        },
        "schedule": {
            "refresh_hour_utc": crawl.REFRESH_HOUR,
            # Null while the daily sweep is switched off.
            "next_run_at": crawl.next_refresh(now, crawl.REFRESH_HOUR) if crawling else None,
        },
    }
