"""Operational status for the crawlers: progress, freshness, failures, drift.

Answers the questions you actually ask mid-sweep — is it moving, where is it, did
anything break, is the index in step with the database — without hand-writing SQL
against source_cursors.

Every section is two functions: `collect_<section>(session, ...)` reads the
database and returns plain data, and the section's own name prints it as
`make status` always has. The admin dashboard (apps/ingestion/admin) renders the
same `collect_*` results, so the page and the terminal cannot disagree.

Everything is read-only. Meilisearch and Redis are optional: if they are not
reachable the relevant section says so and the rest still prints, because "how is
the crawl going" should not depend on the search index being up.

    python -m worker.status [--source SOURCE] [--runs N]
    (also: python scripts/status.py, which runs this)
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
from sqlalchemy import and_, func, or_, select

DIM, BOLD, RED, YELLOW, GREEN, RESET = (
    "\033[2m",
    "\033[1m",
    "\033[31m",
    "\033[33m",
    "\033[32m",
    "\033[0m",
)

#: How long after its last finished run an open cycle with nothing running is
#: still "between runs" rather than "stalled".
STALLED_AFTER = timedelta(hours=36)


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


# --------------------------------------------------------------------------- #
# Sweep progress
# --------------------------------------------------------------------------- #


async def collect_declared_partitions(session) -> dict:
    """How many partitions each configured source *has*, and which failed to load.

    Cursor rows are created lazily, as each partition is first swept, so counting
    them understates the denominator badly mid-sweep: 86 rows into a 301-partition
    source reads as "85/86 done" when it is really 85/301.

    A source whose row no longer builds is reported, because the worker skips
    it too and it would otherwise just quietly stop being swept. Loads the
    adapters (`worker.sources.registry`), which `collect_product_details` reads.
    """
    try:
        from worker.sources.registry import _REGISTRY, load_adapters

        errors = await load_adapters(session)
    except Exception as exc:  # noqa: BLE001 — status still works without the adapters
        return {"failed": str(exc), "errors": {}, "empty": False, "partitions": {}}
    return {
        "failed": None,
        "errors": errors,
        "empty": not _REGISTRY,
        "partitions": {sid: len(adapter.partitions()) for sid, adapter in _REGISTRY.items()},
    }


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


async def collect_sweep_progress(session, source_filter: str | None) -> dict:
    """Per-source cycle progress, from the durable cursors.

    `state` is one of: `paused` (disabled in sources.toml, or paused by a
    person: `disabled` and `paused` say which), `running`, `between` (an open
    cycle, nothing running, a run finished within `STALLED_AFTER`), `stalled`,
    or `idle` (the last cycle completed; cursors reset).
    """
    declared = await collect_declared_partitions(session)
    sources = {
        row.source_id: row
        for row in (
            await session.execute(
                select(Source.source_id, Source.enabled, Source.paused_at, Source.paused_by)
                .add_columns(Source.pause_note)
                .order_by(Source.source_id)
            )
        ).all()
    }
    active = await _active_sources(session)
    finished = await _last_finished(session)
    query = select(SourceCursor).order_by(SourceCursor.source, SourceCursor.partition_key)
    if source_filter:
        query = query.where(SourceCursor.source == source_filter)
    cursors = (await session.execute(query)).scalars().all()

    by_source: dict[str, list[SourceCursor]] = {}
    for cursor in cursors:
        by_source.setdefault(cursor.source, []).append(cursor)

    out = []
    now = datetime.now(timezone.utc)
    for source, rows in by_source.items():
        done = sum(1 for r in rows if r.exhausted)
        total = declared["partitions"].get(source, len(rows))
        starts = [r.cycle_started_at for r in rows if r.cycle_started_at]
        row = sources.get(source)
        disabled = row is not None and not row.enabled
        pause = (
            {"at": row.paused_at, "by": row.paused_by, "note": row.pause_note}
            if row is not None and row.paused_at is not None
            else None
        )
        last = finished.get(source)
        if disabled or pause:
            # The daily run skips it on purpose, so an open cycle here is not
            # a stalled one.
            state = "paused"
        elif starts:
            if source in active:
                state = "running"
            else:
                # The daily run sweeps a slice, so between runs an open cycle with
                # nothing running is the normal state. It is stalled only when no
                # run has finished for longer than a day and a half: the cron, a
                # crash or a blocking host is keeping the cycle from moving.
                recent = last is not None and now - last < STALLED_AFTER
                state = "between" if recent else "stalled"
        else:
            # Cursors reset when a cycle completes, so "no cycle open" with rows
            # present means the last sweep finished — not that nothing ran.
            state = "idle"
            done = total
        out.append(
            {
                "source": source,
                "done": done,
                "total": total,
                "state": state,
                "disabled": disabled,
                "paused": pause,
                "cycle_started_at": min(starts) if starts else None,
                "active_since": active.get(source),
                "last_finished": last,
                # Partitions mid-flight are the interesting ones: they carry the resume point.
                "pending": [
                    (r.partition_key, r.next_page)
                    for r in rows
                    if not r.exhausted and r.next_page > 1
                ],
            }
        )
    return {"declared": declared, "sources": out}


def _pause_text(entry: dict) -> str:
    reasons = []
    if entry["disabled"]:
        reasons.append("enabled = false in sources.toml")
    if entry["paused"]:
        pause = entry["paused"]
        said = f"paused by {pause['by']} ({_age(pause['at'])})"
        if pause.get("note"):
            said += f": {pause['note']}"
        reasons.append(said)
    return "; ".join(reasons)


async def sweep_progress(session, source_filter: str | None) -> None:
    """Per-source cycle progress, from the durable cursors."""
    _header("SWEEP PROGRESS")
    data = await collect_sweep_progress(session, source_filter)
    declared = data["declared"]
    if declared["failed"]:
        print(f"  {RED}could not load sources: {declared['failed']}{RESET}")
    for source_id, error in declared["errors"].items():
        print(f"  {RED}{source_id}: not loaded, so not being swept — {error}{RESET}")
    if declared["empty"]:
        print(f"  {YELLOW}the sources table is empty — run `make sources`{RESET}")
    if not data["sources"]:
        print(f"  {DIM}no cursors yet — nothing has been swept{RESET}")
        return

    for entry in data["sources"]:
        source, done, total = entry["source"], entry["done"], entry["total"]
        started = entry["cycle_started_at"]
        if entry["state"] == "paused":
            state = f"{DIM}paused{RESET}"
            cycle = f"paused: {_pause_text(entry)}; the daily run skips it"
            if started:
                cycle += f" (cycle started {_age(started)})"
        elif entry["state"] == "running":
            state = f"{YELLOW}running{RESET}"
            cycle = f"cycle started {_age(started)}, run active since {_age(entry['active_since'])}"
        elif entry["state"] in ("between", "stalled"):
            state = (
                f"{GREEN}between runs{RESET}"
                if entry["state"] == "between"
                else f"{RED}stalled{RESET}"
            )
            cycle = (
                f"cycle started {_age(started)}, no run active"
                f" (last finished {_age(entry['last_finished'])})"
            )
        else:
            cycle = "idle — last sweep completed"
            state = f"{GREEN}idle{RESET}"

        print(f"  {source:22s} {_bar(done, total)} {done:>4}/{total} partitions  {state}")
        print(f"  {DIM}{'':22s} {cycle}{RESET}")
        for partition, page in entry["pending"][:5]:
            print(f"  {DIM}{'':22s} resumes at {partition} page {page}{RESET}")


# --------------------------------------------------------------------------- #
# Runs and cycles
# --------------------------------------------------------------------------- #


async def collect_recent_runs(session, source_filter: str | None, limit: int) -> list[dict]:
    query = select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(limit)
    if source_filter:
        query = query.where(IngestionRun.source == source_filter)
    runs = (await session.execute(query)).scalars().all()
    out = []
    for run in runs:
        stats = run.stats or {}
        out.append(
            {
                "id": run.id,
                "source": run.source,
                "status": str(run.status),
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "seen": run.items_seen,
                "created": run.items_created,
                "updated": run.items_updated,
                "failed": run.items_failed,
                "archived": stats.get("archived", 0),
                "errors": [str(m) for m in stats.get("errors", [])],
                "error": run.error,
                # Checks only the adapter can make (a Wix sitemap product on no gallery).
                "warnings": [
                    str(m) for m in (stats.get("source_report") or {}).get("warnings", [])
                ],
                "stopped": stats.get("stopped"),
                "limit": stats.get("limit"),
            }
        )
    return out


async def recent_runs(session, source_filter: str | None, limit: int) -> None:
    _header(f"RECENT RUNS (last {limit})")
    runs = await collect_recent_runs(session, source_filter, limit)
    if not runs:
        print(f"  {DIM}no runs recorded{RESET}")
        return

    for run in runs:
        colour = {"success": GREEN, "partial": YELLOW, "failed": RED}.get(run["status"], "")
        errors = run["errors"]
        print(
            f"  {_age(run['started_at']):>9}  {run['source']:20s} {colour}{run['status']:8s}{RESET}"
            f" seen={run['seen']:<6} new={run['created']:<6} upd={run['updated']:<6}"
            f" fail={run['failed']:<4} archived={run['archived']}"
        )
        for message in errors[:2]:
            print(f"  {RED}{'':11s}! {message[:96]}{RESET}")
        if len(errors) > 2:
            print(f"  {RED}{'':11s}! ... {len(errors) - 2} more{RESET}")
        for message in run["warnings"][:2]:
            print(f"  {YELLOW}{'':11s}? {message[:96]}{RESET}")


async def collect_cycle_history(session, source_filter: str | None, days: int = 30) -> dict:
    """Health of past sweeps, so the current one can be judged against a baseline.

    Watching only the cycle in flight tells you nothing about whether it is going
    well. This is the comparison: how often runs succeed, how much they fail, and
    when a full sweep last actually completed.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = (
        select(IngestionRun)
        .where(IngestionRun.started_at >= since)
        .order_by(IngestionRun.started_at.desc())
    )
    if source_filter:
        query = query.where(IngestionRun.source == source_filter)
    runs = (await session.execute(query)).scalars().all()

    by_source: dict[str, list[IngestionRun]] = {}
    for run in runs:
        by_source.setdefault(run.source, []).append(run)

    sources = []
    for source, rows in sorted(by_source.items()):
        # Cycle stamps only exist for sweeps that actually completed.
        completed = [(r, c) for r in rows if (c := (r.stats or {}).get("cycle"))]
        last = None
        if completed:
            run, cycle = completed[0]
            last = {
                "finished_at": run.finished_at,
                "minutes": cycle.get("cycle_seconds", 0) / 60,
                "partitions": cycle.get("cycle_partitions", "?"),
            }
        sources.append(
            {
                "source": source,
                "runs": len(rows),
                "ok": sum(1 for r in rows if str(r.status) == "success"),
                "partial": sum(1 for r in rows if str(r.status) == "partial"),
                "failed": sum(1 for r in rows if str(r.status) == "failed"),
                "items": sum(r.items_seen for r in rows),
                "bad": sum(r.items_failed for r in rows),
                "archived": sum((r.stats or {}).get("archived", 0) for r in rows),
                "last_complete": last,
            }
        )

    # Repeated identical errors are the signal that something is properly broken,
    # as opposed to one flaky page.
    problems: dict[tuple[str, str], int] = {}
    for run in runs:
        for message in (run.stats or {}).get("errors", []):
            key = (run.source, str(message)[:70])
            problems[key] = problems.get(key, 0) + 1
    frequent = [
        {"source": source, "message": message, "count": count}
        for (source, message), count in sorted(problems.items(), key=lambda kv: -kv[1])[:4]
    ]
    return {"days": days, "sources": sources, "frequent_errors": frequent}


async def cycle_history(session, source_filter: str | None, days: int = 30) -> None:
    _header(f"CYCLE HISTORY (last {days}d)")
    data = await collect_cycle_history(session, source_filter, days)
    if not data["sources"]:
        print(f"  {DIM}no runs in this window{RESET}")
        return

    print(
        f"  {DIM}{'source':22s} {'runs':>5} {'ok':>4} {'part':>5} {'fail':>5}"
        f" {'items':>8} {'bad':>5} {'archived':>9}  last complete sweep{RESET}"
    )
    for s in data["sources"]:
        if s["last_complete"]:
            c = s["last_complete"]
            last = f"{_age(c['finished_at'])} ({c['minutes']:.0f}m, {c['partitions']} partitions)"
        else:
            last = f"{DIM}none recorded{RESET}"
        colour = RED if s["failed"] else (YELLOW if s["partial"] else GREEN)
        print(
            f"  {s['source']:22s} {s['runs']:>5} {colour}{s['ok']:>4}{RESET} {s['partial']:>5}"
            f" {s['failed']:>5} {s['items']:>8} {s['bad']:>5} {s['archived']:>9}  {last}"
        )

    if data["frequent_errors"]:
        print(f"\n  {DIM}most frequent errors in window{RESET}")
        for e in data["frequent_errors"]:
            print(f"  {RED}x{e['count']:<4}{RESET} {e['source']}: {e['message']}")


async def collect_cycle_budget(session, source_filter: str | None, days: int = 14) -> dict:
    """Sources with `target_cycle_days`: their latest run's page budget, by source."""
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
    return dict(sorted(latest.items()))


async def cycle_budget(session, source_filter: str | None, days: int = 14) -> None:
    """Sources with `target_cycle_days`: their latest run's page budget, and where it leads.

    The budget is what the cycle still owes over the days the target leaves,
    capped by `max_pages_per_run`. "ceiling-limited" means the cap, not the
    target, is setting the pace: the cycle will run past the target unless the
    ceiling is raised.
    """
    latest = await collect_cycle_budget(session, source_filter, days)
    if not latest:
        return
    _header("CYCLE TARGETS")
    for source, b in latest.items():
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


# --------------------------------------------------------------------------- #
# T1, T4/T12
# --------------------------------------------------------------------------- #


async def collect_short_page_end(session, source_filter: str | None, days: int = 45) -> list[dict]:
    """T1, per source: is ending a partition on a short page safe to switch on?

    In shadow (the default) a run only notes where a short-page stop would
    have ended each partition, and the next page says whether it was right
    (`stats.source_report.short_page`). Tallied here over every full run since
    the start of the source's last completed cycle, so "0 disagreements" over
    a window covering a whole cycle is the plan's bar for setting
    `end_on_short_page = "live"`. A disagreement is a short page that was not
    the last: live, it would have lost the rest of the partition.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = (
        select(IngestionRun)
        .where(
            IngestionRun.started_at >= since,
            # Every full run, those without a tally too: the window's first
            # run must carry one for the window to be a cycle of shadow.
            ~IngestionRun.stats.has_key("limit"),
        )
        .order_by(IngestionRun.started_at.desc())
    )
    if source_filter:
        query = query.where(IngestionRun.source == source_filter)
    by_source: dict[str, list[IngestionRun]] = {}
    for run in (await session.execute(query)).scalars():
        by_source.setdefault(run.source, []).append(run)
    tallies = {
        source: runs
        for source, runs in by_source.items()
        if any(((r.stats or {}).get("source_report") or {}).get("short_page") for r in runs)
    }
    out = []
    for source, runs in sorted(tallies.items()):
        # From the start of the newest completed cycle: one whole cycle, plus
        # whatever of the next has run since.
        start = next((s for r in runs if (s := _cycle_start(r.stats))), None)
        # A run belongs to the window if it was still going when the cycle
        # began: the one that stamped its first cursor started just before.
        window = [
            r for r in runs if start is None or r.finished_at is None or r.finished_at >= start
        ]
        reports = [
            report
            for r in window
            if (report := ((r.stats or {}).get("source_report") or {}).get("short_page"))
        ]
        mode = reports[0].get("mode", "?") if reports else "?"
        shadow = [r for r in reports if r.get("mode") == "shadow"]
        compared = sum(int(r.get("compared") or 0) for r in shadow)
        wrong = sum(int(r.get("disagreements") or 0) for r in shadow)
        # A whole cycle in shadow: the window's first run already carried a
        # tally, so no run of the cycle predates the shadow.
        covered = bool(window) and bool(
            ((window[-1].stats or {}).get("source_report") or {}).get("short_page")
        )
        out.append(
            {
                "source": source,
                "mode": mode,
                "since": start,
                "days": days,
                "saved": sum(
                    int(r.get("saved") or 0) for r in (reports if mode == "live" else shadow)
                ),
                "compared": compared,
                "disagreements": wrong,
                "covered": covered,
                "ready": mode != "live"
                and not wrong
                and bool(compared)
                and start is not None
                and covered,
                "disagreed": [d for r in reports for d in r.get("disagreed") or []],
            }
        )
    return out


async def short_page_end(session, source_filter: str | None, days: int = 45) -> None:
    tallies = await collect_short_page_end(session, source_filter, days)
    if not tallies:
        return
    _header("SHORT-PAGE END (T1)")
    for t in tallies:
        source, start = t["source"], t["since"]
        span = f"since {start:%Y-%m-%d}, a full cycle" if start else f"last {days}d, no full cycle"
        if t["mode"] == "live":
            print(
                f"  {source:22s} short-page stop: {GREEN}live{RESET}, {t['saved']} requests saved ({span})"
            )
            continue
        wrong, compared = t["disagreements"], t["compared"]
        colour = RED if wrong else (GREEN if compared else DIM)
        line = (
            f"  {source:22s} short-page stop: {t['mode']}, {compared} partitions compared,"
            f" {colour}{wrong} disagreements{RESET}, would save {t['saved']} requests ({span})"
        )
        if not t["covered"] and start is not None:
            line += f"  {DIM}not all of the cycle in shadow{RESET}"
        if t["ready"]:
            line += f'  {GREEN}ready: end_on_short_page = "live"{RESET}'
        print(line)
        if t["disagreed"]:
            print(f"  {RED}{'':22s} not the last page: {', '.join(t['disagreed'][:5])}{RESET}")


async def collect_archive_confirmation(
    session, source_filter: str | None, days: int = 45
) -> dict[str, tuple[datetime, dict]]:
    """T4/T12: each source's last cycle-end confirmation, `{source: (started, report)}`.

    Candidates are the listings a completed cycle did not see. "kept" were
    still listed when asked (a sweep skip, not a removal), "absent" were
    archived, and "held" are waiting for the next run: the cycle stays open,
    capped at one cycle, after which they archive as before.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = (
        select(IngestionRun.source, IngestionRun.started_at, IngestionRun.stats["archive_confirm"])
        .where(IngestionRun.started_at >= since, IngestionRun.stats.has_key("archive_confirm"))
        .order_by(IngestionRun.started_at.desc())
    )
    if source_filter:
        query = query.where(IngestionRun.source == source_filter)
    latest: dict[str, tuple[datetime, dict]] = {}
    for source, started, report in (await session.execute(query)).all():
        latest.setdefault(source, (started, report or {}))
    return dict(sorted(latest.items()))


async def archive_confirmation(session, source_filter: str | None, days: int = 45) -> None:
    latest = await collect_archive_confirmation(session, source_filter, days)
    if not latest:
        return
    _header("CONFIRM BEFORE ARCHIVING (T4/T12)")
    for source, (started, r) in latest.items():
        line = (
            f"  {source:22s} {_age(started)}: {r.get('candidates', 0)} candidates,"
            f" kept {r.get('kept', 0)}, archived {r.get('absent', 0)}"
        )
        if r.get("via"):
            line += f" via {r['via']}"
        if r.get("held_by_sitemap") is not None:
            line += f" ({r['held_by_sitemap']} held by the sitemap)"
        if r.get("held"):
            line += f"  {YELLOW}{r['held']} held for the next run{RESET}"
        if r.get("failed"):
            line += f"  {RED}failed: {str(r['failed'])[:60]}{RESET}"
        if r.get("overdue"):
            line += f"  {YELLOW}waited a cycle: archived as before{RESET}"
        print(line)


# --------------------------------------------------------------------------- #
# Identity and robots.txt
# --------------------------------------------------------------------------- #


async def collect_crawler_identity(session, source_filter: str | None) -> dict:
    """Who each source is crawled as: configured, and what its last run actually sent.

    `identity` in a source's config is "browser" (the default) or "makhzanbot"
    (honest User-Agent, Web Bot Auth signed when MAKHZANBOT_SIGNING_KEY is set);
    see docs/crawler-identity.md. The last run's `stats.identity` is the
    evidence: a source switched to makhzanbot whose runs go out unsigned has no
    key on the worker, and a shop's edge cannot verify it. `keyid` is this
    environment's signing key, if it holds one (the admin service does not).
    """
    from makhzan_schemas import botauth

    query = select(Source.source_id, Source.config, Source.enabled).order_by(Source.source_id)
    if source_filter:
        query = query.where(Source.source_id == source_filter)
    sources = (await session.execute(query)).all()
    runs = select(IngestionRun.source, IngestionRun.stats["identity"]).where(
        IngestionRun.stats.has_key("identity")
    )
    last: dict[str, dict] = {}
    for source, identity in (
        await session.execute(runs.order_by(IngestionRun.started_at.desc()))
    ).all():
        last.setdefault(source, identity or {})

    keyid, key_error = None, None
    try:
        key = botauth.configured_key()
        keyid = botauth.Signer(key).keyid if key is not None else None
    except Exception as exc:  # noqa: BLE001 — a bad key must not hide the rest
        key_error = str(exc)
    rows = []
    for source_id, config, enabled in sources:
        configured = (config or {}).get("identity", "browser")
        seen = last.get(source_id)
        rows.append(
            {
                "source": source_id,
                "configured": configured,
                "enabled": enabled,
                "seen": seen,
                "unverifiable": configured == "makhzanbot"
                and seen is not None
                and not seen.get("signed"),
                "changed": seen is not None and seen.get("name") != configured,
            }
        )
    return {"keyid": keyid, "key_error": key_error, "key_env": botauth.KEY_ENV, "sources": rows}


async def crawler_identity(session, source_filter: str | None) -> None:
    data = await collect_crawler_identity(session, source_filter)
    if not data["sources"]:
        return
    _header("CRAWLER IDENTITY")
    if data["key_error"]:
        print(f"  {RED}signing key here is unreadable: {data['key_error']}{RESET}")
    elif data["keyid"]:
        print(f"  {DIM}signing key here: keyid {data['keyid']}{RESET}")
    else:
        print(f"  {DIM}no signing key in this environment ({data['key_env']}){RESET}")
    for row in data["sources"]:
        seen = row["seen"]
        if seen is None:
            sent = f"{DIM}no run has recorded it yet{RESET}"
        else:
            signed = "signed" if seen.get("signed") else "unsigned"
            sent = f"last run: {seen.get('name')}, {signed}"
            if seen.get("keyid"):
                sent += f" (keyid {seen['keyid'][:12]}…)"
        line = f"  {row['source']:22s} {row['configured']:11s} {sent}"
        if row["unverifiable"]:
            line += f"  {YELLOW}unverifiable: no key on the worker{RESET}"
        if row["changed"]:
            line += f"  {YELLOW}changed since the last run{RESET}"
        if not row["enabled"]:
            line += f"  {DIM}(disabled){RESET}"
        print(line)


#: A host served from a stale robots.txt copy older than this is flagged.
STALE_COPY_WARN_DAYS = 7


async def collect_robots_health(session, source_filter: str | None) -> dict[str, dict]:
    """What robots.txt said to each source's latest run (`stats.robots`), and why a run stopped.

    `{source: {"hosts": {host: {"state", "copy_age_days", "error"}}, "stopped": str|None}}`.
    "fetched" and "no_rules" (a 4xx) are the normal states; "stale" is a copy
    standing in for an unreadable file, flagged past `STALE_COPY_WARN_DAYS`;
    anything else means the host was refused for that run (RFC 9309).
    """
    query = (
        select(IngestionRun.source, IngestionRun.stats["robots"], IngestionRun.stats["stopped"])
        .where(IngestionRun.stats.has_key("robots"))
        .order_by(IngestionRun.started_at.desc())
    )
    if source_filter:
        query = query.where(IngestionRun.source == source_filter)
    latest: dict[str, dict] = {}
    for source, robots, stopped in (await session.execute(query)).all():
        latest.setdefault(source, {"hosts": robots or {}, "stopped": stopped})
    return dict(sorted(latest.items()))


async def robots_health(session, source_filter: str | None) -> None:
    latest = await collect_robots_health(session, source_filter)
    if not latest:
        return
    _header("ROBOTS.TXT (latest run)")
    for source, entry in latest.items():
        parts = []
        for host, said in sorted(entry["hosts"].items()):
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
        if entry["stopped"]:
            print(f"  {'':22s} {YELLOW}run stopped early: {entry['stopped']}{RESET}")


# --------------------------------------------------------------------------- #
# Crosswalk drift
# --------------------------------------------------------------------------- #


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


async def collect_crosswalk_drift(session, source_filter: str | None, days: int = 30) -> list[dict]:
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
    longer counts as never matched. "Matches the source" (`matches`) is only
    said when the runs read cover a completed cycle and no run's stored list
    was capped; otherwise a clean slice is just that (`clean_slice`). A run
    cut off mid-sweep reports the names it saw up to its last page (the
    pipeline checkpoints them).
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Each source's newest completed cycle, looked up on its own: a cycle that
    # started before `since` must still be read from its start, or its first
    # runs would be cut off while the window still claimed to cover it.
    cycle_query = (
        select(IngestionRun.source, IngestionRun.stats["cycle"])
        .where(IngestionRun.stats.has_key("cycle"))
        .order_by(IngestionRun.source, IngestionRun.started_at.desc())
        .distinct(IngestionRun.source)
    )
    if source_filter:
        cycle_query = cycle_query.where(IngestionRun.source == source_filter)
    cycle_starts = {
        source: start
        for source, cycle in (await session.execute(cycle_query)).all()
        if (start := _cycle_start({"cycle": cycle}))
    }

    # Per source, from the earlier of `since` and its own cycle's start: one
    # source with an old cycle must not drag every other source's read back.
    # Only the runs that checked, and only the keys this reads.
    ended = func.coalesce(IngestionRun.finished_at, IngestionRun.started_at)
    windows = [
        and_(IngestionRun.source == source, ended >= min(since, start))
        for source, start in cycle_starts.items()
    ]
    windows.append(and_(IngestionRun.source.notin_(list(cycle_starts)), ended >= since))
    query = (
        select(IngestionRun.source, ended, IngestionRun.stats["crosswalk"])
        .where(IngestionRun.stats.has_key("crosswalk"), or_(*windows))
        .order_by(IngestionRun.started_at.desc())
    )
    if source_filter:
        query = query.where(IngestionRun.source == source_filter)
    # (ended, crosswalk) per source, newest first.
    runs_by_source: dict[str, list[tuple[datetime, dict]]] = {}
    for source, run_ended, drift in (await session.execute(query)).all():
        if isinstance(drift, dict):
            runs_by_source.setdefault(source, []).append((run_ended, drift))
    configs = dict((await session.execute(select(Source.source_id, Source.config))).all())

    out = []
    for source in sorted(runs_by_source):
        checked_all = runs_by_source[source]
        cycle_start = cycle_starts.get(source)
        start = cycle_start or since
        checked = [drift for run_ended, drift in checked_all if run_ended >= start]
        entry = {
            "source": source,
            "crosswalk": (configs.get(source) or {}).get("crosswalk"),
            "scope": "this cycle" if cycle_start else f"in {days}d, no completed cycle",
            "days": days,
            "checked": len(checked),
            "covered": False,
            "why_unfiltered": None,
            "unmapped": {},
            "hidden": None,
            "unused": [],
            "unused_count": 0,
            "unused_capped": False,
        }
        out.append(entry)
        if not checked:
            continue
        newest = checked[0]
        entry["covered"] = cycle_start is not None or "unused" in newest

        mapped, ignored, why_unfiltered = _current_crosswalk(configs.get(source))
        entry["why_unfiltered"] = why_unfiltered
        known = mapped | ignored
        unmapped: dict[str, int] = {}
        hidden: tuple[int | None, int] | None = None  # what the newest capped run left out
        for drift in checked:
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
        entry["unmapped"] = dict(sorted(unmapped.items(), key=lambda kv: -kv[1]))
        entry["hidden"] = hidden

        complete = next((drift for _, drift in checked_all if "unused" in drift), {})
        unused = list(complete.get("unused") or [])
        unused_count = complete.get("unused_count", len(unused))
        entry["unused_capped"] = unused_count > len(unused)
        if not why_unfiltered:
            unused = [n for n in unused if normalize_category_name(n) in mapped]
            unused_count = len(unused)
        entry["unused"], entry["unused_count"] = unused, unused_count
    return out


def drift_is_clean(entry: dict) -> bool:
    """Nothing unmapped, nothing unused, no capped list: nothing to act on."""
    return entry["checked"] > 0 and not (entry["unmapped"] or entry["unused"] or entry["hidden"])


async def crosswalk_drift(session, source_filter: str | None, days: int = 30) -> None:
    _header("CROSSWALK DRIFT")
    entries = await collect_crosswalk_drift(session, source_filter, days)
    for e in entries:
        source = e["source"]
        if not e["checked"]:
            print(f"  {source:22s} 0 runs checked ({e['scope']})")
            continue
        note = f"    {DIM}not filtered by the current crosswalk: {e['why_unfiltered']}{RESET}"
        if drift_is_clean(e):
            if e["covered"]:
                print(f"  {source:22s} {GREEN}crosswalk matches the source{RESET}")
            else:
                print(
                    f"  {source:22s} no unmapped names seen this cycle"
                    f" {DIM}(no completed cycle in the last {days}d to vouch for the rest){RESET}"
                )
            if e["why_unfiltered"]:
                print(note)
            continue
        print(f"  {source:22s} {e['checked']} runs checked ({e['scope']})")
        if e["why_unfiltered"]:
            print(note)
        unmapped = e["unmapped"]
        if unmapped:
            print(
                f"    {YELLOW}{len(unmapped)} unmapped{RESET} "
                f"({sum(unmapped.values())} listings) — new or renamed:"
            )
            for name, count in list(unmapped.items())[:6]:
                print(f"      {count:5d}  {name[:62]}")
        if e["hidden"] is not None:
            # A run stored only its biggest names. What it left out is unknown,
            # so the report never calls this source clean.
            names, listings = e["hidden"]
            print(
                f"    {YELLOW}+{'?' if names is None else names} more names"
                f" / {listings} listings not listed{RESET}"
                f" {DIM}(a run's stored list was capped; may include names since mapped){RESET}"
            )
        if e["unused"]:
            # Only reported after a complete sweep, so this really means "gone".
            at_least = "at least " if e["unused_capped"] else ""
            print(
                f"    {YELLOW}{at_least}{e['unused_count']} entries never matched{RESET}"
                f" — retired or renamed away:"
            )
            print(f"      {DIM}{', '.join(e['unused'][:6])}{RESET}")
    if not entries:
        print(f"  {DIM}no mapped source has reported yet{RESET}")


# --------------------------------------------------------------------------- #
# Product details
# --------------------------------------------------------------------------- #


async def collect_product_details(session, source_filter: str | None) -> dict:
    """What every shop's listings carry, and, for shops read page by page, the queue.

    One entry per source, the paused ones too. The coverage is measured on
    active listings as the site shows them (the list feed's fields with any
    product page laid over): the share with a description, a spec table, more
    than one photo, and documents. A shop whose feed already carries all of it
    is read in the sweep itself, at no extra request, so a drop there means the
    feed changed, not that a page stage fell behind.

    For a source that reads product pages, `queue` splits what is still due by
    reason, in the order a run spends its budget: the change token moved, the
    page was never read, or it was read longer ago than `max_age_days`. A
    source still backfilling shows a large "never"; one past it, a trickle of
    "changed". Needs the adapters loaded (`collect_declared_partitions`), since
    the settings live in sources.toml.

    `reader`: `pages_on`, `pages_off` (details.enabled = false),
    `not_configured` (the adapter reads pages but has no `details` key) or
    `feed_only` (no product-page reader).
    """
    try:
        from worker.details import queue_counts
        from worker.sources.base import SourceAdapter
        from worker.sources.registry import _REGISTRY
    except Exception as exc:  # noqa: BLE001 — status still works without the worker
        return {"unavailable": type(exc).__name__, "sources": []}
    sources = {sid: a for sid, a in _REGISTRY.items() if not source_filter or sid == source_filter}
    coverage = await content_coverage(session) if sources else {}
    out = []
    for source_id, adapter in sorted(sources.items(), key=lambda kv: (not kv[1].enabled, kv[0])):
        settings = adapter.details
        reads_pages = type(adapter).fetch_details is not SourceAdapter.fetch_details
        if settings is not None and settings.enabled:
            reader = "pages_on"
        elif settings is not None:
            reader = "pages_off"
        elif reads_pages:
            reader = "not_configured"
        else:
            reader = "feed_only"
        entry = {
            "source": source_id,
            "enabled": adapter.enabled,
            "reader": reader,
            "per_run": settings.per_run if settings is not None else None,
            "coverage": coverage.get(source_id),
            "queue": None,
            "last": None,
        }
        out.append(entry)
        if settings is None:
            continue
        # A card hash cannot see a description edit, so its refresh age adapts
        # per listing (T10); a shop's own last-write token keeps the setting.
        adaptive = adapter.token_kind == "card_hash"
        entry["queue"] = {
            "token_kind": adapter.token_kind,
            "max_age_days": settings.max_age_days,
            "adaptive": adaptive,
            **await queue_counts(session, source_id, settings, adaptive=adaptive),
        }
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
            entry["last"] = {
                "started_at": last.started_at,
                "fetched": summary.get("fetched", 0),
                "failed": summary.get("failed", 0),
                "stopped": summary.get("stopped"),
            }
    return {"unavailable": None, "sources": out}


async def product_details(session, source_filter: str | None) -> None:
    _header("PRODUCT DETAILS")
    data = await collect_product_details(session, source_filter)
    if data["unavailable"]:
        print(f"  {DIM}worker not importable ({data['unavailable']}){RESET}")
        return
    if not data["sources"]:
        print(f"  {DIM}no sources loaded{RESET}")
        return
    for e in data["sources"]:
        source_id = e["source"]
        state = {
            "pages_on": f"{GREEN}product pages on{RESET}, {e['per_run']} a run",
            "pages_off": f"{YELLOW}product pages off{RESET} (details.enabled = false)",
            "not_configured": f"{YELLOW}product pages not configured{RESET} (no `details` key)",
            "feed_only": "list feed only — no product-page reader, no extra requests",
        }[e["reader"]]
        if not e["enabled"]:
            state += f" {DIM}[source paused]{RESET}"
        print(f"  {source_id:22s} {state}")
        c = e["coverage"]
        if c is None or not c["active"]:
            print(f"  {DIM}{'':22s} no active listings{RESET}")
        else:
            print(
                f"  {'':22s} {c['active']} active:  description {_pct(c['description'], c['active'])}"
                f"   specs {_pct(c['specs'], c['active'])}"
                f"   2+ photos {_pct(c['gallery'], c['active'])}"
                f"   documents {_pct(c['documents'], c['active'])}"
            )
        q = e["queue"]
        if q is None:
            continue
        refresh = (
            f"adaptive from {q['max_age_days']}d" if q["adaptive"] else f"{q['max_age_days']}d"
        )
        print(
            f"  {'':22s} token: {q['token_kind'] or 'none'}, refresh after"
            f" {refresh}   have page {q['fetched']}"
            f"   due: changed {q['changed']}, never fetched {q['never_fetched']},"
            f" stale by age {q['stale']}   backing off {q['backing_off']}"
        )
        if e["last"] is not None:
            last = e["last"]
            line = (
                f"last run {_age(last['started_at'])}: fetched {last['fetched']},"
                f" failed {last['failed']}"
            )
            if last["stopped"]:
                line += f", stopped: {str(last['stopped'])[:60]}"
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


# --------------------------------------------------------------------------- #
# Catalog, review queue, index, AI, worker queue
# --------------------------------------------------------------------------- #


async def collect_catalog(session, source_filter: str | None) -> list[dict]:
    """Listings per supplier and department, with the things that signal a broken crawl."""
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
    keys = ("shop", "domain", "total", "archived", "uncategorized", "unpriced", "on_request")
    return [
        {**dict(zip(keys, row[:7], strict=True)), "verified": row[7]}
        for row in rows
        if not source_filter or source_filter in row[0]
    ]


async def catalog(session, source_filter: str | None) -> None:
    """Listings per supplier, with the things that signal a broken crawl."""
    _header("CATALOG")
    rows = await collect_catalog(session, None)
    if not rows:
        print(f"  {DIM}no listings{RESET}")
        return

    print(
        f"  {DIM}{'supplier':22s} {'domain':12s} {'total':>7} {'archived':>9}"
        f" {'uncat':>7} {'no price':>9} {'on req':>7}  verified{RESET}"
    )
    for r in rows:
        if source_filter and source_filter not in r["shop"]:
            continue
        # Uncategorized and unpriced are the two failure modes that look fine in
        # aggregate counts but make a listing useless in the UI.
        uncategorized, unpriced = r["uncategorized"], r["unpriced"]
        uncat = f"{YELLOW}{uncategorized:>7}{RESET}" if uncategorized else f"{uncategorized:>7}"
        noprice = f"{YELLOW}{unpriced:>9}{RESET}" if unpriced else f"{unpriced:>9}"
        print(
            f"  {r['shop']:22s} {r['domain']:12s} {r['total']:>7} {r['archived']:>9} {uncat}"
            f" {noprice} {r['on_request']:>7}  {_age(r['verified'])}"
        )
    await price_history(session)


async def collect_price_history(session) -> dict[str, int]:
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
    return {"day": day, "week": week}


async def price_history(session) -> None:
    counts = await collect_price_history(session)
    print(
        f"  price observations recorded: {counts['day']} in the last 24 h,"
        f" {counts['week']} in the last 7 d"
    )


async def collect_review_queue(session) -> dict[str, int]:
    rows = (
        await session.execute(
            select(ReviewQueueItem.reason, func.count(ReviewQueueItem.id))
            .where(ReviewQueueItem.status == ReviewStatus.PENDING)
            .group_by(ReviewQueueItem.reason)
        )
    ).all()
    return {str(reason): count for reason, count in rows}


async def review_queue(session) -> None:
    _header("REVIEW QUEUE")
    rows = await collect_review_queue(session)
    if not rows:
        print(f"  {GREEN}empty{RESET}")
        return
    for reason, count in rows.items():
        print(f"  {reason:24s} {count}")


async def collect_index_drift(session) -> dict:
    """The search index is a projection of the DB; a mismatch means it is stale.

    `{"products", "indexed", "error"}`: `indexed` is None when Meilisearch
    could not be asked, and `error` says why.
    """
    # Listed products: merged-away and withdrawn ones keep their rows (permanent
    # ids) but are never indexed.
    product_count = (
        await session.execute(select(func.count(Product.id)).where(Product.is_listed()))
    ).scalar_one()
    try:
        from makhzan_schemas.search import INDEX_NAME

        from worker.indexer import get_client

        stats = get_client().index(INDEX_NAME).get_stats()
        indexed = stats.number_of_documents
    except Exception as exc:  # noqa: BLE001 — status must not fail because search is down
        return {"products": product_count, "indexed": None, "error": type(exc).__name__}
    return {"products": product_count, "indexed": indexed, "error": None}


async def index_drift(session) -> None:
    _header("SEARCH INDEX")
    data = await collect_index_drift(session)
    if data["indexed"] is None:
        print(f"  products in db: {data['products']}")
        print(f"  {DIM}meilisearch unreachable ({data['error']}) — skipping drift check{RESET}")
        return
    drift = data["products"] - data["indexed"]
    verdict = (
        f"{GREEN}in sync{RESET}"
        if drift == 0
        else f"{YELLOW}drift {drift:+d} — run make reindex{RESET}"
    )
    print(f"  products in db: {data['products']}   indexed: {data['indexed']}   {verdict}")


async def collect_ai_matching(session) -> dict:
    """`makhzan_schemas.ai.status.collect`, or `{"error": ...}` if it could not be read."""
    try:
        from makhzan_schemas.ai.status import collect

        return await collect(session)
    except Exception as exc:  # noqa: BLE001 - status must not fail on one section
        await session.rollback()
        return {"error": f"{type(exc).__name__}: {exc}"}


async def ai_matching(session) -> None:
    """AI matching: mode, queue, throughput, workers, decisions (makhzan_schemas.ai.status)."""
    _header("AI MATCHING")
    data = await collect_ai_matching(session)
    if "error" in data:
        print(f"  {DIM}unavailable ({data['error']}){RESET}")
        return
    from makhzan_schemas.ai.status import format_text

    text = format_text(data)
    if data["flags"] or data["rescore_due"]["no_job"] or data["rescore_due"]["dead_job"]:
        text = text.replace("  flags ", f"  {YELLOW}flags{RESET} ", 1)
    print(text)


def collect_queue_depth() -> dict:
    """arq's queue length, or why Redis could not be asked."""
    url = os.getenv("REDIS_URL", "redis://localhost:6379")
    try:
        import redis

        client = redis.from_url(url, socket_connect_timeout=2)
        return {"url": url, "queued": client.zcard("arq:queue"), "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "queued": None, "error": type(exc).__name__}


def queue_depth() -> None:
    _header("WORKER QUEUE")
    data = collect_queue_depth()
    if data["queued"] is None:
        print(f"  {DIM}redis unreachable at {data['url']} ({data['error']}){RESET}")
    else:
        print(f"  arq jobs queued: {data['queued']}")


async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="makhzan crawler status")
    parser.add_argument("--source", help="limit to one source id")
    parser.add_argument("--runs", type=int, default=8, help="how many recent runs to show")
    args = parser.parse_args(argv)

    async with SessionLocal() as session:
        await sweep_progress(session, args.source)
        await cycle_history(session, args.source)
        await cycle_budget(session, args.source)
        await short_page_end(session, args.source)
        await archive_confirmation(session, args.source)
        await crawler_identity(session, args.source)
        await robots_health(session, args.source)
        await recent_runs(session, args.source, args.runs)
        await crosswalk_drift(session, args.source)
        await product_details(session, args.source)
        await catalog(session, args.source)
        await review_queue(session)
        await index_drift(session)
        await ai_matching(session)
    queue_depth()
    print()


if __name__ == "__main__":
    asyncio.run(main())
