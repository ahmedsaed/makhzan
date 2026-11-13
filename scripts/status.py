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
from makhzan_schemas.domains.crosswalks import fold_names, load_crosswalk, normalize_category_name
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


async def cycle_budget(session, source_filter: str | None, days: int = 14) -> None:
    """Sources with `target_cycle_days`: their latest run's page budget, and where it leads.

    The budget is what the cycle still owes over the days the target leaves,
    capped by `max_pages_per_run`. "ceiling-limited" means the cap, not the
    target, is setting the pace: the cycle will run past the target unless the
    ceiling is raised.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = (
        select(IngestionRun.source, IngestionRun.stats["budget"])
        .where(IngestionRun.started_at >= since, IngestionRun.stats.has_key("budget"))
        .order_by(IngestionRun.started_at.desc())
    )
    if source_filter:
        query = query.where(IngestionRun.source == source_filter)
    latest: dict[str, dict] = {}
    for source, budget in (await session.execute(query)).all():
        latest.setdefault(source, budget or {})
    if not latest:
        return
    _header("CYCLE TARGETS")
    for source, b in sorted(latest.items()):
        target = b.get("target_cycle_days")
        line = f"  {source:22s} target {target:g}d  budget {b.get('pages')} pages/run"
        line += f"  (ceiling {b.get('ceiling') or 'none'})"
        if "projected_cycle_days" not in b:
            print(f"{line}  {DIM}{b.get('basis', 'no plan yet')}{RESET}")
            continue
        projected = b["projected_cycle_days"]
        colour = YELLOW if projected > target else GREEN
        line += f"  projected {colour}{projected:g}d{RESET}"
        if b.get("ceiling_limited"):
            line += f"  {YELLOW}ceiling-limited (planned {b.get('planned')}){RESET}"
        print(line)


async def crawler_identity(session, source_filter: str | None) -> None:
    """Who each source is crawled as: configured, and what its last run actually sent.

    `identity` in a source's config is "browser" (the default) or "makhzanbot"
    (honest User-Agent, Web Bot Auth signed when MAKHZANBOT_SIGNING_KEY is set);
    see docs/crawler-identity.md. The last run's `stats.identity` is the
    evidence: a source switched to makhzanbot whose runs go out unsigned has no
    key on the worker, and a shop's edge cannot verify it.
    """
    from makhzan_schemas import botauth

    query = select(Source.source_id, Source.config, Source.enabled).order_by(Source.source_id)
    if source_filter:
        query = query.where(Source.source_id == source_filter)
    sources = (await session.execute(query)).all()
    if not sources:
        return
    runs = select(IngestionRun.source, IngestionRun.stats["identity"]).where(
        IngestionRun.stats.has_key("identity")
    )
    last: dict[str, dict] = {}
    for source, identity in (
        await session.execute(runs.order_by(IngestionRun.started_at.desc()))
    ).all():
        last.setdefault(source, identity or {})

    _header("CRAWLER IDENTITY")
    try:
        key = botauth.configured_key()
    except Exception as exc:  # noqa: BLE001 — a bad key must not hide the rest
        print(f"  {RED}signing key here is unreadable: {exc}{RESET}")
        key = None
    if key is not None:
        print(f"  {DIM}signing key here: keyid {botauth.Signer(key).keyid}{RESET}")
    else:
        print(f"  {DIM}no signing key in this environment ({botauth.KEY_ENV}){RESET}")
    for source_id, config, enabled in sources:
        configured = (config or {}).get("identity", "browser")
        seen = last.get(source_id)
        if seen is None:
            sent = f"{DIM}no run has recorded it yet{RESET}"
        else:
            signed = "signed" if seen.get("signed") else "unsigned"
            sent = f"last run: {seen.get('name')}, {signed}"
            if seen.get("keyid"):
                sent += f" (keyid {seen['keyid'][:12]}…)"
        line = f"  {source_id:22s} {configured:11s} {sent}"
        if configured == "makhzanbot" and seen is not None and not seen.get("signed"):
            line += f"  {YELLOW}unverifiable: no key on the worker{RESET}"
        if seen is not None and seen.get("name") != configured:
            line += f"  {YELLOW}changed since the last run{RESET}"
        if not enabled:
            line += f"  {DIM}(disabled){RESET}"
        print(line)


#: A host served from a stale robots.txt copy older than this is flagged.
STALE_COPY_WARN_DAYS = 7


async def robots_health(session, source_filter: str | None) -> None:
    """What robots.txt said to each source's latest run (`stats.robots`), and why a run stopped.

    "fetched" and "no rules" (a 4xx) are the normal answers and print as one
    quiet line. A stale copy standing in for an unreadable file is shown with
    its age, flagged past a week; "unavailable" means the host was refused for
    that run (RFC 9309: unreadable and no usable copy).
    """
    query = (
        select(IngestionRun.source, IngestionRun.stats["robots"], IngestionRun.stats["stopped"])
        .where(IngestionRun.stats.has_key("robots"))
        .order_by(IngestionRun.started_at.desc())
    )
    if source_filter:
        query = query.where(IngestionRun.source == source_filter)
    latest: dict[str, tuple[dict, str | None]] = {}
    for source, robots, stopped in (await session.execute(query)).all():
        latest.setdefault(source, (robots or {}, stopped))
    if not latest:
        return
    _header("ROBOTS.TXT (latest run)")
    for source, (robots, stopped) in sorted(latest.items()):
        parts = []
        for host, said in sorted(robots.items()):
            state = said.get("state", "?")
            age = said.get("copy_age_days")
            if state in ("fetched", "no_rules"):
                parts.append(f"{DIM}{host} {state.replace('_', ' ')}{RESET}")
            elif state == "stale":
                colour = RED if (age or 0) > STALE_COPY_WARN_DAYS else YELLOW
                parts.append(
                    f"{colour}{host} unreadable, using a copy {age:g}d old "
                    f"({said.get('error', '')}){RESET}"
                )
            else:
                parts.append(f"{RED}{host} UNAVAILABLE: {said.get('error', '')}{RESET}")
        print(f"  {source:22s} " + "; ".join(parts))
        if stopped:
            print(f"  {'':22s} {YELLOW}run stopped early: {stopped}{RESET}")


def _current_crosswalk(config: dict | None) -> tuple[set[str], set[str], str | None]:
    """The source's crosswalk as it stands now: (mapped, ignored) folded names.

    Read from the file, not from the runs, so a mapping or an `ignore` entry
    added since a run reported drift takes the name off the report at once.
    The third value says why the filter could not be applied, if it could not.
    """
    name = (config or {}).get("crosswalk")
    if not name:
        return set(), set(), "no crosswalk named in the source's config"
    try:
        loaded = load_crosswalk(name)
    except (OSError, ValueError) as exc:
        return set(), set(), f"crosswalk {name!r} could not be loaded: {exc}"
    return fold_names(loaded.categories), fold_names(loaded.ignore), None


def _cycle_start(stats: dict | None) -> datetime | None:
    started = ((stats or {}).get("cycle") or {}).get("cycle_started_at")
    try:
        return datetime.fromisoformat(started) if started else None
    except ValueError:
        return None


async def crosswalk_drift(session, source_filter: str | None, days: int = 30) -> None:
    """Categories a supplier has added, renamed or retired since the crosswalk was written.

    A crosswalk is a snapshot. When a supplier renames a category the mapping
    stops matching and those listings quietly lose it — which looks exactly like
    the supplier discontinuing stock. This makes the difference visible.

    One run is not the catalogue: a paced source sweeps a slice a day, and a
    run only reports the names its slice showed. So `unmapped` is the union of
    every run that checked since the start of the last completed cycle (or over
    `days`, when there is none), newest count per name. Runs without a
    `crosswalk` key — before clean checks were recorded, or that saw nothing —
    add nothing and never count as clean. `unused` comes from the newest run
    that swept the whole catalogue itself, the only kind that carries the key.

    Both are then filtered by the crosswalk as it stands now: a name since
    mapped or ignored leaves the report at once, and an entry since removed no
    longer counts as never matched. "Matches the source" is only said when the
    runs read cover a completed cycle and no run's stored list was capped;
    otherwise a clean slice is just that. A run cut off mid-sweep reports the
    names it saw up to its last page (the pipeline checkpoints them).
    """
    _header("CROSSWALK DRIFT")
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Each source's newest completed cycle, looked up on its own: a cycle that
    # started before `since` must still be read from its start, or its first
    # runs would be cut off while the window still claimed to cover it.
    cycle_query = (
        select(IngestionRun.source, IngestionRun.stats)
        .where(IngestionRun.stats.has_key("cycle"))
        .order_by(IngestionRun.source, IngestionRun.started_at.desc())
        .distinct(IngestionRun.source)
    )
    if source_filter:
        cycle_query = cycle_query.where(IngestionRun.source == source_filter)
    cycle_starts = {
        source: start
        for source, stats in (await session.execute(cycle_query)).all()
        if (start := _cycle_start(stats))
    }
    floor = min([since, *cycle_starts.values()])

    query = (
        select(IngestionRun)
        .where(func.coalesce(IngestionRun.finished_at, IngestionRun.started_at) >= floor)
        .order_by(IngestionRun.started_at.desc())
    )
    if source_filter:
        query = query.where(IngestionRun.source == source_filter)
    runs_by_source: dict[str, list] = {}
    for run in (await session.execute(query)).scalars().all():
        runs_by_source.setdefault(run.source, []).append(run)
    configs = dict((await session.execute(select(Source.source_id, Source.config))).all())

    reported = False
    for source in sorted(runs_by_source):
        runs = runs_by_source[source]  # newest first
        checked_all = [r for r in runs if isinstance((r.stats or {}).get("crosswalk"), dict)]
        if not checked_all:
            continue
        reported = True

        # The window: from the start of the newest completed cycle (a run
        # belongs to it if it was still going then: the cycle's first cursor is
        # stamped after its first run starts), else the last `days`.
        cycle_start = cycle_starts.get(source)
        start = cycle_start or since
        checked = [r for r in checked_all if (r.finished_at or r.started_at) >= start]
        scope = "this cycle" if cycle_start else f"in {days}d, no completed cycle"
        if not checked:
            print(f"  {source:22s} 0 runs checked ({scope})")
            continue
        newest = checked[0].stats["crosswalk"]
        covered = cycle_start is not None or "unused" in newest

        mapped, ignored, why_unfiltered = _current_crosswalk(configs.get(source))
        known = mapped | ignored
        unmapped: dict[str, int] = {}
        hidden: tuple[int | None, int] | None = None  # what the newest capped run left out
        for run in checked:
            drift = run.stats["crosswalk"]
            listed = drift.get("unmapped") or {}
            for name, count in listed.items():
                if normalize_category_name(name) not in known:
                    unmapped.setdefault(name, count)
            # Runs from before `unmapped_count` was stored say only the listings.
            total_names = drift.get("unmapped_count")
            more_names = None if total_names is None else total_names - len(listed)
            more_listings = (drift.get("unmapped_listings") or 0) - sum(listed.values())
            if hidden is None and ((more_names or 0) > 0 or more_listings > 0):
                hidden = (more_names, more_listings)

        complete = next(
            (r.stats["crosswalk"] for r in checked_all if "unused" in r.stats["crosswalk"]), {}
        )
        unused = list(complete.get("unused") or [])
        unused_count = complete.get("unused_count", len(unused))
        unused_capped = unused_count > len(unused)
        if not why_unfiltered:
            unused = [n for n in unused if normalize_category_name(n) in mapped]
            unused_count = len(unused)

        note = f"    {DIM}not filtered by the current crosswalk: {why_unfiltered}{RESET}"
        if not unmapped and not unused and hidden is None:
            if covered:
                print(f"  {source:22s} {GREEN}crosswalk matches the source{RESET}")
            else:
                print(
                    f"  {source:22s} no unmapped names seen this cycle"
                    f" {DIM}(no completed cycle in the last {days}d to vouch for the rest){RESET}"
                )
            if why_unfiltered:
                print(note)
            continue
        print(f"  {source:22s} {len(checked)} runs checked ({scope})")
        if why_unfiltered:
            print(note)
        if unmapped:
            unmapped = dict(sorted(unmapped.items(), key=lambda kv: -kv[1]))
            print(
                f"    {YELLOW}{len(unmapped)} unmapped{RESET} "
                f"({sum(unmapped.values())} listings) — new or renamed:"
            )
            for name, count in list(unmapped.items())[:6]:
                print(f"      {count:5d}  {name[:62]}")
        if hidden is not None:
            # A run stored only its biggest names. What it left out is unknown,
            # so the report never calls this source clean.
            names, listings = hidden
            print(
                f"    {YELLOW}+{'?' if names is None else names} more names"
                f" / {listings} listings not listed{RESET}"
                f" {DIM}(a run's stored list was capped; may include names since mapped){RESET}"
            )
        if unused:
            # Only reported after a complete sweep, so this really means "gone".
            at_least = "at least " if unused_capped else ""
            print(
                f"    {YELLOW}{at_least}{unused_count} entries never matched{RESET}"
                f" — retired or renamed away:"
            )
            print(f"      {DIM}{', '.join(unused[:6])}{RESET}")
    if not reported:
        print(f"  {DIM}no mapped source has reported yet{RESET}")


async def product_details(session, source_filter: str | None) -> None:
    """What every shop's listings carry, and, for shops read page by page, the queue.

    One block per source, the paused ones too. The coverage line is measured on
    active listings as the site shows them (the list feed's fields with any
    product page laid over): the share with a description, a spec table, more
    than one photo, and documents. A shop whose feed already carries all of it
    is read in the sweep itself, at no extra request, so a drop there means the
    feed changed, not that a page stage fell behind.

    For a source that reads product pages, a second line splits what is still
    due by reason, in the order a run spends its budget: the change token moved,
    the page was never read, or it was read longer ago than `max_age_days`. A
    source still backfilling shows a large "never"; one past it, a trickle of
    "changed". Needs the adapters (the settings live in sources.toml).
    """
    _header("PRODUCT DETAILS")
    try:
        from worker.details import queue_counts
        from worker.sources.base import SourceAdapter
        from worker.sources.registry import _REGISTRY
    except Exception as exc:  # noqa: BLE001 — status still works without the worker
        print(f"  {DIM}worker not importable ({type(exc).__name__}){RESET}")
        return
    sources = {sid: a for sid, a in _REGISTRY.items() if not source_filter or sid == source_filter}
    if not sources:
        print(f"  {DIM}no sources loaded{RESET}")
        return
    coverage = await content_coverage(session)
    for source_id, adapter in sorted(sources.items(), key=lambda kv: (not kv[1].enabled, kv[0])):
        settings = adapter.details
        reads_pages = type(adapter).fetch_details is not SourceAdapter.fetch_details
        if settings is not None and settings.enabled:
            state = f"{GREEN}product pages on{RESET}, {settings.per_run} a run"
        elif settings is not None:
            state = f"{YELLOW}product pages off{RESET} (details.enabled = false)"
        elif reads_pages:
            state = f"{YELLOW}product pages not configured{RESET} (no `details` key)"
        else:
            state = "list feed only — no product-page reader, no extra requests"
        if not adapter.enabled:
            state += f" {DIM}[source paused]{RESET}"
        print(f"  {source_id:22s} {state}")
        c = coverage.get(source_id)
        if c is None or not c["active"]:
            print(f"  {DIM}{'':22s} no active listings{RESET}")
        else:
            print(
                f"  {'':22s} {c['active']} active:  description {_pct(c['description'], c['active'])}"
                f"   specs {_pct(c['specs'], c['active'])}"
                f"   2+ photos {_pct(c['gallery'], c['active'])}"
                f"   documents {_pct(c['documents'], c['active'])}"
            )
        if settings is None:
            continue
        counts = await queue_counts(session, source_id, settings)
        print(
            f"  {'':22s} token: {adapter.token_kind or 'none'}, refresh after"
            f" {settings.max_age_days}d   have page {counts['fetched']}"
            f"   due: changed {counts['changed']}, never fetched {counts['never_fetched']},"
            f" stale by age {counts['stale']}   backing off {counts['backing_off']}"
        )
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
        if last is not None:
            summary = (last.stats or {}).get("details") or {}
            line = (
                f"last run {_age(last.started_at)}: fetched {summary.get('fetched', 0)},"
                f" failed {summary.get('failed', 0)}"
            )
            if summary.get("stopped"):
                line += f", stopped: {str(summary['stopped'])[:60]}"
            print(f"  {DIM}{'':22s} {line}{RESET}")


def _pct(part: int, whole: int) -> str:
    return f"{round(100 * part / whole):>3}%"


async def content_coverage(session) -> dict[str, dict[str, int]]:
    """Per source, how many active listings carry each kind of content."""
    attrs = Listing.attributes
    rows = (
        await session.execute(
            select(
                Listing.source,
                func.count(Listing.id),
                func.count(Listing.id).filter(func.coalesce(Listing.description_en, "") != ""),
                func.count(Listing.id).filter(attrs.has_key("specs")),
                func.count(Listing.id).filter(func.jsonb_array_length(Listing.images) > 1),
                func.count(Listing.id).filter(attrs.has_key("documents")),
            )
            .where(Listing.status == ListingStatus.ACTIVE)
            .group_by(Listing.source)
        )
    ).all()
    return {
        r[0]: {
            "active": r[1],
            "description": r[2],
            "specs": r[3],
            "gallery": r[4],
            "documents": r[5],
        }
        for r in rows
    }


async def catalog(session, source_filter: str | None) -> None:
    """Listings per supplier, with the things that signal a broken crawl."""
    _header("CATALOG")
    # "Contact for price" is the shop's choice, not a broken crawl, so it is
    # counted apart. Read as the API reads it: JSON true and no price.
    on_request = Listing.attributes.contains({"price_on_request": True})
    rows = (
        await session.execute(
            select(
                Supplier.slug,
                Listing.domain,
                func.count(Listing.id),
                func.count(Listing.id).filter(Listing.status == ListingStatus.ARCHIVED),
                func.count(Listing.id).filter(Listing.category_id.is_(None)),
                func.count(Listing.id).filter(Listing.price.is_(None), ~on_request),
                func.count(Listing.id).filter(Listing.price.is_(None), on_request),
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
        f" {'uncat':>7} {'no price':>9} {'on req':>7}  verified{RESET}"
    )
    for slug, domain, total, archived, uncategorized, unpriced, on_req, verified in rows:
        if source_filter and source_filter not in slug:
            continue
        # Uncategorized and unpriced are the two failure modes that look fine in
        # aggregate counts but make a listing useless in the UI.
        uncat = f"{YELLOW}{uncategorized:>7}{RESET}" if uncategorized else f"{uncategorized:>7}"
        noprice = f"{YELLOW}{unpriced:>9}{RESET}" if unpriced else f"{unpriced:>9}"
        print(
            f"  {slug:22s} {domain:12s} {total:>7} {archived:>9} {uncat} {noprice}"
            f" {on_req:>7}  {_age(verified)}"
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
    # Listed products: merged-away and withdrawn ones keep their rows (permanent
    # ids) but are never indexed.
    product_count = (
        await session.execute(select(func.count(Product.id)).where(Product.is_listed()))
    ).scalar_one()
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
        await cycle_budget(session, args.source)
        await crawler_identity(session, args.source)
        await robots_health(session, args.source)
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
