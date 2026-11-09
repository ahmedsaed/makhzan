"""Operational status for the crawlers: progress, freshness, failures, drift.

Answers the questions you actually ask mid-sweep — is it moving, where is it, did
anything break, is the index in step with the database — without hand-writing SQL
against source_cursors.

Everything is read-only. Meilisearch and Redis are optional: if they are not
reachable the relevant section says so and the rest still prints, because "how is
the crawl going" should not depend on the search index being up.

    python scripts/status.py [--source SOURCE] [--runs N]
"""

from __future__ import annotations

import argparse
import asyncio
import os
from datetime import datetime, timedelta, timezone

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.enums import IngestionStatus, ListingStatus, ReviewStatus
from makhzan_schemas.models import (
    IngestionRun,
    Listing,
    PriceObservation,
    Product,
    ReviewQueueItem,
    Source,
    SourceCursor,
    Supplier,
)
from sqlalchemy import func, select

DIM, BOLD, RED, YELLOW, GREEN, RESET = (
    "\033[2m",
    "\033[1m",
    "\033[31m",
    "\033[33m",
    "\033[32m",
    "\033[0m",
)


def _age(moment: datetime | None) -> str:
    if moment is None:
        return "never"
    delta = datetime.now(timezone.utc) - moment
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{delta.total_seconds() / 60:.0f}m ago"
    if hours < 48:
        return f"{hours:.0f}h ago"
    return f"{hours / 24:.0f}d ago"


def _bar(done: int, total: int, width: int = 24) -> str:
    if not total:
        return "-" * width
    filled = round(width * done / total)
    return "█" * filled + "░" * (width - filled)


def _header(text: str) -> None:
    print(f"\n{BOLD}{text}{RESET}")


async def _declared_partitions(session) -> dict[str, int]:
    """How many partitions each configured source *has*.

    Cursor rows are created lazily, as each partition is first swept, so counting
    them understates the denominator badly mid-sweep: 86 rows into a 301-partition
    source reads as "85/86 done" when it is really 85/301.

    A source whose row no longer builds is printed here, because the worker skips
    it too and it would otherwise just quietly stop being swept.
    """
    try:
        from worker.sources.registry import _REGISTRY, load_adapters

        errors = await load_adapters(session)
    except Exception as exc:  # noqa: BLE001 — status still works without the adapters
        print(f"  {RED}could not load sources: {exc}{RESET}")
        return {}
    for source_id, error in errors.items():
        print(f"  {RED}{source_id}: not loaded, so not being swept — {error}{RESET}")
    if not _REGISTRY:
        print(f"  {YELLOW}the sources table is empty — run `make sources`{RESET}")
    return {sid: len(adapter.partitions()) for sid, adapter in _REGISTRY.items()}


async def _active_sources(session) -> dict[str, datetime]:
    """Sources with a run currently RUNNING, by start time."""
    rows = (
        await session.execute(
            select(IngestionRun.source, func.max(IngestionRun.started_at))
            .where(IngestionRun.status == IngestionStatus.RUNNING)
            .group_by(IngestionRun.source)
        )
    ).all()
    return dict(rows)


async def _last_finished(session) -> dict[str, datetime]:
    rows = (
        await session.execute(
            select(IngestionRun.source, func.max(IngestionRun.finished_at))
            .where(IngestionRun.finished_at.is_not(None))
            .group_by(IngestionRun.source)
        )
    ).all()
    return dict(rows)


async def sweep_progress(session, source_filter: str | None) -> None:
    """Per-source cycle progress, from the durable cursors."""
    _header("SWEEP PROGRESS")
    declared = await _declared_partitions(session)
    paused = {
        row
        for row in (
            await session.execute(select(Source.source_id).where(Source.enabled.is_(False)))
        ).scalars()
    }
    active = await _active_sources(session)
    finished = await _last_finished(session)
    query = select(SourceCursor).order_by(SourceCursor.source, SourceCursor.partition_key)
    if source_filter:
        query = query.where(SourceCursor.source == source_filter)
    cursors = (await session.execute(query)).scalars().all()
    if not cursors:
        print(f"  {DIM}no cursors yet — nothing has been swept{RESET}")
        return

    by_source: dict[str, list[SourceCursor]] = {}
    for cursor in cursors:
        by_source.setdefault(cursor.source, []).append(cursor)

    for source, rows in by_source.items():
        done = sum(1 for r in rows if r.exhausted)
        total = declared.get(source, len(rows))
        starts = [r.cycle_started_at for r in rows if r.cycle_started_at]

        if source in paused:
            # `enabled = false` in sources.toml: the daily run skips it on
            # purpose, so an open cycle here is not a stalled one.
            state = f"{DIM}paused{RESET}"
            cycle = "paused: enabled = false in sources.toml; the daily run skips it"
            if starts:
                cycle += f" (cycle started {_age(min(starts))})"
        elif starts:
            cycle = f"cycle started {_age(min(starts))}"
            if source in active:
                # A run is actually executing right now.
                state = f"{YELLOW}running{RESET}"
                cycle += f", run active since {_age(active[source])}"
            else:
                # The daily run sweeps a slice, so between runs an open cycle with
                # nothing running is the normal state. It is stalled only when no
                # run has finished for longer than a day and a half: the cron, a
                # crash or a blocking host is keeping the cycle from moving.
                last = finished.get(source)
                recent = last is not None and datetime.now(timezone.utc) - last < timedelta(
                    hours=36
                )
                state = f"{GREEN}between runs{RESET}" if recent else f"{RED}stalled{RESET}"
                cycle += f", no run active (last finished {_age(last)})"
        else:
            # Cursors reset when a cycle completes, so "no cycle open" with rows
            # present means the last sweep finished — not that nothing ran.
            cycle = "idle — last sweep completed"
            state = f"{GREEN}idle{RESET}"
            done = total

        print(f"  {source:22s} {_bar(done, total)} {done:>4}/{total} partitions  {state}")
        print(f"  {DIM}{'':22s} {cycle}{RESET}")

        # Partitions mid-flight are the interesting ones: they carry the resume point.
        pending = [r for r in rows if not r.exhausted and r.next_page > 1]
        for row in pending[:5]:
            print(f"  {DIM}{'':22s} resumes at {row.partition_key} page {row.next_page}{RESET}")


async def recent_runs(session, source_filter: str | None, limit: int) -> None:
    _header(f"RECENT RUNS (last {limit})")
    query = select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit)
    if source_filter:
        query = query.where(IngestionRun.source == source_filter)
    runs = (await session.execute(query)).scalars().all()
    if not runs:
        print(f"  {DIM}no runs recorded{RESET}")
        return

    for run in runs:
        colour = {"success": GREEN, "partial": YELLOW, "failed": RED}.get(str(run.status), "")
        errors = run.stats.get("errors", []) if run.stats else []
        archived = (run.stats or {}).get("archived", 0)
        print(
            f"  {_age(run.started_at):>9}  {run.source:20s} {colour}{str(run.status):8s}{RESET}"
            f" seen={run.items_seen:<6} new={run.items_created:<6} upd={run.items_updated:<6}"
            f" fail={run.items_failed:<4} archived={archived}"
        )
        for message in errors[:2]:
            print(f"  {RED}{'':11s}! {str(message)[:96]}{RESET}")
        if len(errors) > 2:
            print(f"  {RED}{'':11s}! ... {len(errors) - 2} more{RESET}")
        # Checks only the adapter can make (a Wix sitemap product on no gallery).
        for message in ((run.stats or {}).get("source_report") or {}).get("warnings", [])[:2]:
            print(f"  {YELLOW}{'':11s}? {str(message)[:96]}{RESET}")


async def cycle_history(session, source_filter: str | None, days: int = 30) -> None:
    """Health of past sweeps, so the current one can be judged against a baseline.

    Watching only the cycle in flight tells you nothing about whether it is going
    well. This is the comparison: how often runs succeed, how much they fail, and
    when a full sweep last actually completed.
    """
    _header(f"CYCLE HISTORY (last {days}d)")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = (
        select(IngestionRun)
        .where(IngestionRun.started_at >= since)
        .order_by(IngestionRun.started_at.desc())
    )
    if source_filter:
        query = query.where(IngestionRun.source == source_filter)
    runs = (await session.execute(query)).scalars().all()
    if not runs:
        print(f"  {DIM}no runs in this window{RESET}")
        return

    by_source: dict[str, list[IngestionRun]] = {}
    for run in runs:
        by_source.setdefault(run.source, []).append(run)

    print(
        f"  {DIM}{'source':22s} {'runs':>5} {'ok':>4} {'part':>5} {'fail':>5}"
        f" {'items':>8} {'bad':>5} {'archived':>9}  last complete sweep{RESET}"
    )
    for source, rows in sorted(by_source.items()):
        ok = sum(1 for r in rows if str(r.status) == "success")
        partial = sum(1 for r in rows if str(r.status) == "partial")
        failed = sum(1 for r in rows if str(r.status) == "failed")
        items = sum(r.items_seen for r in rows)
        bad = sum(r.items_failed for r in rows)
        archived = sum((r.stats or {}).get("archived", 0) for r in rows)

        # Cycle stamps only exist for sweeps that actually completed.
        cycles = [(r, (r.stats or {}).get("cycle")) for r in rows]
        completed = [(r, c) for r, c in cycles if c]
        if completed:
            run, cycle = completed[0]
            mins = cycle.get("cycle_seconds", 0) / 60
            last = f"{_age(run.finished_at)} ({mins:.0f}m, {cycle.get('cycle_partitions', '?')} partitions)"
        else:
            last = f"{DIM}none recorded{RESET}"

        colour = RED if failed else (YELLOW if partial else GREEN)
        print(
            f"  {source:22s} {len(rows):>5} {colour}{ok:>4}{RESET} {partial:>5} {failed:>5}"
            f" {items:>8} {bad:>5} {archived:>9}  {last}"
        )

    # Repeated identical errors are the signal that something is properly broken,
    # as opposed to one flaky page.
    problems: dict[str, int] = {}
    for run in runs:
        for message in (run.stats or {}).get("errors", []):
            key = f"{run.source}: {str(message)[:70]}"
            problems[key] = problems.get(key, 0) + 1
    if problems:
        print(f"\n  {DIM}most frequent errors in window{RESET}")
        for key, count in sorted(problems.items(), key=lambda kv: -kv[1])[:4]:
            print(f"  {RED}x{count:<4}{RESET} {key}")


async def crosswalk_drift(session, source_filter: str | None, days: int = 30) -> None:
    """Categories a supplier has added, renamed or retired since the crosswalk was written.

    A crosswalk is a snapshot. When a supplier renames a category the mapping
    stops matching and those listings quietly lose it — which looks exactly like
    the supplier discontinuing stock. This makes the difference visible.
    """
    _header("CROSSWALK DRIFT")
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = (
        select(IngestionRun)
        .where(IngestionRun.started_at >= since)
        .order_by(IngestionRun.started_at.desc())
    )
    if source_filter:
        query = query.where(IngestionRun.source == source_filter)

    latest: dict[str, dict] = {}
    for run in (await session.execute(query)).scalars().all():
        drift = (run.stats or {}).get("crosswalk")
        if drift and run.source not in latest:
            latest[run.source] = drift
    if not latest:
        print(f"  {DIM}no mapped source has reported yet{RESET}")
        return

    for source, drift in sorted(latest.items()):
        unmapped = drift.get("unmapped") or {}
        unused = drift.get("unused") or []
        if not unmapped and not unused:
            print(f"  {source:22s} {GREEN}crosswalk matches the source{RESET}")
            continue
        print(f"  {source:22s} {drift.get('observed', '?')} category names seen")
        if unmapped:
            print(
                f"    {YELLOW}{len(unmapped)} unmapped{RESET} "
                f"({drift.get('unmapped_listings', 0)} listings) — new or renamed:"
            )
            for name, count in list(unmapped.items())[:6]:
                print(f"      {count:5d}  {name[:62]}")
        if unused:
            # Only reported after a complete cycle, so this really means "gone".
            print(
                f"    {YELLOW}{drift.get('unused_count', len(unused))} entries never matched{RESET}"
                f" — retired or renamed away:"
            )
            print(f"      {DIM}{', '.join(unused[:6])}{RESET}")


async def product_details(session, source_filter: str | None) -> None:
    """Product-page details: how many listings are due, and why, per source that reads them.

    Due by reason, in the order a run spends its budget: the change token moved,
    the page was never read, or it was read longer ago than `max_age_days`. A
    source still backfilling shows a large "never"; one past it should show a
    trickle of "changed". Needs the adapters (the settings live in sources.toml).
    """
    _header("PRODUCT DETAILS")
    try:
        from worker.details import queue_counts
        from worker.sources.registry import _REGISTRY
    except Exception as exc:  # noqa: BLE001 — status still works without the worker
        print(f"  {DIM}worker not importable ({type(exc).__name__}){RESET}")
        return
    sources = {
        sid: a
        for sid, a in _REGISTRY.items()
        if a.details is not None and (not source_filter or sid == source_filter)
    }
    if not sources:
        print(f"  {DIM}no source reads product pages{RESET}")
        return
    for source_id, adapter in sorted(sources.items()):
        settings = adapter.details
        counts = await queue_counts(session, source_id, settings)
        last = (
            await session.execute(
                select(IngestionRun)
                .where(
                    IngestionRun.source == source_id,
                    IngestionRun.stats["details"].is_not(None),
                )
                .order_by(IngestionRun.started_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        state = (
            f"{GREEN}on{RESET}, {settings.per_run} a run"
            if settings.enabled
            else f"{DIM}off (details.enabled = false){RESET}"
        )
        print(
            f"  {source_id:22s} {state}  token: {adapter.token_kind or 'none'},"
            f" refresh after {settings.max_age_days}d"
        )
        print(
            f"  {'':22s} have details {counts['fetched']:>6}   due: changed {counts['changed']}"
            f", never fetched {counts['never_fetched']}, stale by age {counts['stale']}"
            f"   backing off {counts['backing_off']}"
        )
        if last is not None:
            summary = (last.stats or {}).get("details") or {}
            line = (
                f"last run {_age(last.started_at)}: fetched {summary.get('fetched', 0)},"
                f" failed {summary.get('failed', 0)}"
            )
            if summary.get("stopped"):
                line += f", stopped: {str(summary['stopped'])[:60]}"
            print(f"  {DIM}{'':22s} {line}{RESET}")


async def catalog(session, source_filter: str | None) -> None:
    """Listings per supplier, with the things that signal a broken crawl."""
    _header("CATALOG")
    rows = (
        await session.execute(
            select(
                Supplier.slug,
                Listing.domain,
                func.count(Listing.id),
                func.count(Listing.id).filter(Listing.status == ListingStatus.ARCHIVED),
                func.count(Listing.id).filter(Listing.category_id.is_(None)),
                func.count(Listing.id).filter(Listing.price.is_(None)),
                func.max(Listing.last_verified_at),
            )
            .join(Listing, Listing.supplier_id == Supplier.id)
            .group_by(Supplier.slug, Listing.domain)
            .order_by(func.count(Listing.id).desc())
        )
    ).all()
    if not rows:
        print(f"  {DIM}no listings{RESET}")
        return

    print(
        f"  {DIM}{'supplier':22s} {'domain':12s} {'total':>7} {'archived':>9}"
        f" {'uncat':>7} {'no price':>9}  verified{RESET}"
    )
    for slug, domain, total, archived, uncategorized, unpriced, verified in rows:
        if source_filter and source_filter not in slug:
            continue
        # Uncategorized and unpriced are the two failure modes that look fine in
        # aggregate counts but make a listing useless in the UI.
        uncat = f"{YELLOW}{uncategorized:>7}{RESET}" if uncategorized else f"{uncategorized:>7}"
        noprice = f"{YELLOW}{unpriced:>9}{RESET}" if unpriced else f"{unpriced:>9}"
        print(
            f"  {slug:22s} {domain:12s} {total:>7} {archived:>9} {uncat} {noprice}"
            f"  {_age(verified)}"
        )
    await price_history(session)


async def price_history(session) -> None:
    """Change points recorded lately. Zero for days while sweeps run means it broke."""
    now = datetime.now(timezone.utc)
    day, week = (
        await session.execute(
            select(
                func.count().filter(PriceObservation.observed_at >= now - timedelta(days=1)),
                func.count().filter(PriceObservation.observed_at >= now - timedelta(days=7)),
            )
        )
    ).one()
    print(f"  price observations recorded: {day} in the last 24 h, {week} in the last 7 d")


async def review_queue(session) -> None:
    _header("REVIEW QUEUE")
    rows = (
        await session.execute(
            select(ReviewQueueItem.reason, func.count(ReviewQueueItem.id))
            .where(ReviewQueueItem.status == ReviewStatus.PENDING)
            .group_by(ReviewQueueItem.reason)
        )
    ).all()
    if not rows:
        print(f"  {GREEN}empty{RESET}")
        return
    for reason, count in rows:
        print(f"  {str(reason):24s} {count}")


async def index_drift(session) -> None:
    """The search index is a projection of the DB; a mismatch means it is stale."""
    _header("SEARCH INDEX")
    product_count = (await session.execute(select(func.count(Product.id)))).scalar_one()
    try:
        from worker.indexer import get_client
        from makhzan_schemas.search import INDEX_NAME

        stats = get_client().index(INDEX_NAME).get_stats()
        indexed = stats.number_of_documents
    except Exception as exc:  # noqa: BLE001 — status must not fail because search is down
        print(f"  products in db: {product_count}")
        print(
            f"  {DIM}meilisearch unreachable ({type(exc).__name__}) — skipping drift check{RESET}"
        )
        return

    drift = product_count - indexed
    verdict = (
        f"{GREEN}in sync{RESET}"
        if drift == 0
        else f"{YELLOW}drift {drift:+d} — run make reindex{RESET}"
    )
    print(f"  products in db: {product_count}   indexed: {indexed}   {verdict}")


def queue_depth() -> None:
    _header("WORKER QUEUE")
    url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        import redis

        client = redis.from_url(url, socket_connect_timeout=2)
        queued = client.zcard("arq:queue")
        print(f"  arq jobs queued: {queued}")
    except Exception as exc:  # noqa: BLE001
        print(f"  {DIM}redis unreachable at {url} ({type(exc).__name__}){RESET}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="makhzan crawler status")
    parser.add_argument("--source", help="limit to one source id")
    parser.add_argument("--runs", type=int, default=8, help="how many recent runs to show")
    args = parser.parse_args()

    async with SessionLocal() as session:
        await sweep_progress(session, args.source)
        await cycle_history(session, args.source)
        await recent_runs(session, args.source, args.runs)
        await crosswalk_drift(session, args.source)
        await product_details(session, args.source)
        await catalog(session, args.source)
        await review_queue(session)
        await index_drift(session)
    queue_depth()
    print()


if __name__ == "__main__":
    asyncio.run(main())
