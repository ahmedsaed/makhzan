"""Freshness report: what the crawler's requests buy, per source (scheduling plan, Phase 0).

`make status` answers "is the crawl moving?". This answers "is it spending its
requests well?": how many it sends, how stale the catalogue gets, how many
changes each request finds, how late they are found, and how often a listing is
archived only to come back. It is the baseline later phases are judged against,
so it is meant to be re-run every week and compared, never tuned against once.

Read-only: one `READ ONLY` transaction, rolled back. Sends nothing to any shop.

    python scripts/freshness.py [--source SOURCE] [--days N] [--exclude SOURCE ...]

The metrics (names from the plan, §3):

M1  Requests. Per run, what it sent: `stats.pacing.requests` (everything that
    went out, robots.txt and retries included), or the sum of
    `stats.requests` for runs from before pacing was recorded. Shown per UTC
    day of the window (mean over the window's days, and the busiest day), and
    for the last completed cycle (runs still going at its start or later and
    started before it closed). `limit=` test runs are left out throughout.

M2  Coverage. Cycle length is `stats.cycle.cycle_seconds` of the last
    completed cycles. Staleness is the age of `last_verified_at` (when the
    price was last read) over the source's active listings, at p50/p90/p99.

M3  Changes per 1,000 requests. A change is a `price_observations` row in the
    window that is not the listing's first and not an archiving row
    (`available` false), whose price, currency or stock signal differs from the
    row before it. Divided by the window's M1 requests, and split by `via`
    (the lane that read it; only "sweep" until later phases). Shop-wide
    repricing waves dominate this, so compare like weeks with like.

    Check log: per listing `checks` (counted reads, at most one a run, from
    `first_checked_at` to `last_checked_at`) and `changes` (reads that found a
    change; never the first), cumulative since the log began. A stock-only
    read (out of stock by id) is a check: it sees stock changes, not price.
    The pooled Cho & Garcia-Molina estimate of the change rate,
    λ = -ln((n - X + 0.5) / (n + 0.5)) / I, is over the intervals between
    reads of listings with 2+ checks: n = Σ(checks - 1), X = Σ changes, and I
    the mean interval, Σ(last_checked_at - first_checked_at) / n (so weighted
    by each listing's checks - 1). Shown as days between changes.

M5  Detection delay: for each change row in the window, `observed_at -
    prev_checked_at`, the listing's previous counted read. The change happened
    in between, so this is how long the site may have shown the old value.
    Median and p90. Empty for changes found on a listing's first counted read.

M6  False archivals. An archiving row (`available` false) is judged once two
    of the source's last cycle lengths (14 days each when unknown) have passed:
    did the listing's next row bring it back within that time? Judged are the
    archivings in a window of `--days` ending two cycles ago; those newer than
    that are printed apart as too recent to judge (window archivings only).

Segments (§0 of the plan). For listings re-read in the window that already had
a price row before it (their baseline: the row in force at the window's
start), the share whose price, stock, or either moved in the window, by:
price band (of the baseline price), stock state at the baseline, and whether
the listing's product is offered by more than one supplier. "share of changes"
is the segment's part of every listing that moved. `--exclude` leaves a source
out of this table, as §0 left shop 2's one bulk reprice out.

Also two Phase 0 measurements that have no other reader yet:
  - validators (T11): of the 2xx responses in the window, the share carrying
    ETag / Last-Modified, from `stats.validators`. Conditional requests are
    worth building only if most pages carry one.
  - category churn (D4): from `stats.categories`, how often a sweep set, moved
    or cleared a stored listing's category.
"""

from __future__ import annotations

import argparse
import asyncio
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from makhzan_schemas.db import SessionLocal
from sqlalchemy import text

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"

PRICE_BANDS = (
    ("no price", None, None),
    ("< 50", 0, 50),
    ("50-200", 50, 200),
    ("200-1,000", 200, 1000),
    (">= 1,000", 1000, None),
)
#: When a source has no completed cycle to measure, M6 assumes this one.
DEFAULT_CYCLE = timedelta(days=7)


def _header(text_: str) -> None:
    print(f"\n{BOLD}{text_}{RESET}")


def _quantile(values: list[float], q: float) -> float | None:
    """The q-quantile of `values` by linear interpolation; None when empty."""
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _days(value: float | None) -> str:
    return "-" if value is None else f"{value:.1f}d"


def _pct(part: int, whole: int) -> str:
    return "-" if not whole else f"{100 * part / whole:.1f}%"


def run_requests(stats: dict | None) -> int | None:
    """What one run sent (M1): `stats.pacing.requests`, else the sum of `stats.requests`.

    None for a run that recorded neither (older than the counting, or cut off
    before it wrote its stats): unknown, never zero.
    """
    stats = stats or {}
    pacing = stats.get("pacing")
    if isinstance(pacing, dict) and isinstance(pacing.get("requests"), int):
        return pacing["requests"]
    requests = stats.get("requests")
    if isinstance(requests, dict):
        return sum(v for v in requests.values() if isinstance(v, int))
    return None


def _sum_known(values: list[int | None]) -> tuple[int | None, bool]:
    """(sum of the known counts or None if none is known, whether any was unknown)."""
    known = [v for v in values if v is not None]
    return (sum(known) if known else None), len(known) < len(values)


def _count(value: int | None, partial: bool) -> str:
    """A request count as printed: "-" unknown, ">=N" when some runs did not say."""
    if value is None:
        return "-"
    return f">={value}" if partial else str(value)


def cho_rate(checks: int, changes: int, interval_days: float) -> float | None:
    """Cho & Garcia-Molina's change-rate estimate, per day: -ln((n-X+0.5)/(n+0.5)) / I."""
    if checks <= 0 or interval_days <= 0:
        return None
    return -math.log((checks - changes + 0.5) / (checks + 0.5)) / interval_days


async def _runs(session, since: datetime, source: str | None) -> list:
    query = """
        SELECT source, started_at, finished_at, stats
        FROM ingestion_runs
        WHERE started_at >= :since AND NOT (stats ? 'limit')
          AND (CAST(:source AS text) IS NULL OR source = :source)
        ORDER BY started_at
    """
    return (await session.execute(text(query), {"since": since, "source": source})).all()


def requests_and_cycles(runs: list, window_start: datetime, now: datetime) -> dict[str, dict]:
    """M1 and M2's cycle length per source, from its runs (oldest first)."""
    out: dict[str, dict] = {}
    days = max(1, math.ceil((now - window_start).total_seconds() / 86400))
    by_source: dict[str, list] = defaultdict(list)
    for row in runs:
        by_source[row.source].append(row)
    for source, rows in by_source.items():
        per_day: Counter = Counter()
        in_window = [row for row in rows if row.started_at >= window_start]
        for row in in_window:
            per_day[row.started_at.date()] += run_requests(row.stats) or 0
        window_total, window_partial = _sum_known([run_requests(r.stats) for r in in_window])
        cycles = [
            (row, (row.stats or {}).get("cycle"))
            for row in rows
            if isinstance((row.stats or {}).get("cycle"), dict)
        ]
        entry: dict = {
            "requests_window": window_total or 0,
            "requests_window_partial": window_partial,
            "requests_per_day": (window_total or 0) / days,
            "requests_max_day": max(per_day.values(), default=0),
            "cycle_days": [round(c.get("cycle_seconds", 0) / 86400, 1) for _, c in cycles[-3:]],
            "cycle_requests": None,
            "cycle_requests_partial": False,
        }
        if cycles:
            _, last = cycles[-1]
            try:
                start = datetime.fromisoformat(last["cycle_started_at"])
                end = datetime.fromisoformat(last["cycle_completed_at"])
            except (KeyError, TypeError, ValueError):
                start = end = None
            if start and end:
                entry["cycle_requests"], entry["cycle_requests_partial"] = _sum_known(
                    [
                        run_requests(r.stats)
                        for r in rows
                        if r.started_at <= end and (r.finished_at is None or r.finished_at >= start)
                    ]
                )
        out[source] = entry
    return out


async def staleness(session, source: str | None) -> dict[str, dict]:
    """M2: active listings' `last_verified_at` age (days) at p50/p90/p99, and the check log."""
    query = """
        SELECT source,
               count(*) AS active,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY age) AS p50,
               percentile_cont(0.9) WITHIN GROUP (ORDER BY age) AS p90,
               percentile_cont(0.99) WITHIN GROUP (ORDER BY age) AS p99
        FROM (
            SELECT source, CAST(extract(epoch FROM now() - last_verified_at) AS float8) / 86400 AS age
            FROM listings
            WHERE status = 'ACTIVE' AND (CAST(:source AS text) IS NULL OR source = :source)
        ) ages
        GROUP BY source
    """
    rows = (await session.execute(text(query), {"source": source})).all()
    return {r.source: {"active": r.active, "p50": r.p50, "p90": r.p90, "p99": r.p99} for r in rows}


async def check_log(session, source: str | None) -> dict[str, dict]:
    """The check log per source: its totals and the pooled change rate (M3)."""
    query = """
        SELECT source, checks, changes,
               CAST(extract(epoch FROM last_checked_at - first_checked_at) AS float8) / 86400
                   AS span
        FROM listings
        WHERE checks > 0 AND first_checked_at IS NOT NULL AND last_checked_at IS NOT NULL
          AND (CAST(:source AS text) IS NULL OR source = :source)
    """
    rows = (await session.execute(text(query), {"source": source})).all()
    out: dict[str, dict] = {}
    by_source: dict[str, list] = defaultdict(list)
    for row in rows:
        by_source[row.source].append(row)
    for src, items in by_source.items():
        # Intervals between reads: the first read of each listing opens one.
        repeat = [r for r in items if r.checks > 1]
        n = sum(r.checks - 1 for r in repeat)
        x = sum(r.changes for r in repeat)
        span = sum(r.span or 0.0 for r in repeat)
        rate = cho_rate(n, x, span / n) if n and span > 0 else None
        out[src] = {
            "listings": len(items),
            "checks": sum(r.checks for r in items),
            "changes": sum(r.changes for r in items),
            "intervals": n,
            "days_between_changes": (1 / rate) if rate else None,
        }
    return out


async def _has_column(session, table: str, column: str) -> bool:
    """Whether the database has the column yet (it may predate the Phase 0 migration)."""
    query = """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = :t AND column_name = :c
    """
    return (await session.execute(text(query), {"t": table, "c": column})).first() is not None


async def changes(
    session, since: datetime, source: str | None, *, has_log: bool = True
) -> tuple[dict[str, Counter], dict[str, dict]]:
    """M3's numerator (change rows in the window per source, by `via`) and M5.

    Before `via` existed every row was the sweep's, so that is what it reads as.
    """
    via = "via" if has_log else "CAST('sweep' AS text) AS via"
    prev = "prev_checked_at" if has_log else "CAST(NULL AS timestamptz) AS prev_checked_at"
    query = f"""
        SELECT l.source, o.via,
               CAST(extract(epoch FROM o.observed_at - o.prev_checked_at) AS float8) / 86400
                   AS delay
        FROM (
            SELECT listing_id, observed_at, {via}, {prev}, available, price, currency,
                   stock_signal,
                   lag(price) OVER w AS p_price, lag(currency) OVER w AS p_currency,
                   lag(stock_signal) OVER w AS p_stock, lag(observed_at) OVER w AS p_at
            FROM price_observations
            WINDOW w AS (PARTITION BY listing_id ORDER BY observed_at)
        ) o
        JOIN listings l ON l.id = o.listing_id
        WHERE o.observed_at >= :since AND o.available AND o.p_at IS NOT NULL
          AND (o.price IS DISTINCT FROM o.p_price OR o.currency <> o.p_currency
               OR o.stock_signal <> o.p_stock)
          AND (CAST(:source AS text) IS NULL OR l.source = :source)
    """
    out: dict[str, Counter] = defaultdict(Counter)
    delays: dict[str, list[float]] = defaultdict(list)
    for row in (await session.execute(text(query), {"since": since, "source": source})).all():
        out[row.source][row.via] += 1
        if row.delay is not None:
            delays[row.source].append(row.delay)
    m5 = {
        src: {"n": len(d), "p50": _quantile(d, 0.5), "p90": _quantile(d, 0.9)}
        for src, d in delays.items()
    }
    return dict(out), m5


async def false_archivals(
    session, now: datetime, days: int, source: str | None, cycles: dict[str, timedelta]
) -> dict[str, dict]:
    """M6: judged archivings and how many came back within two cycles; the too recent apart."""
    window = timedelta(days=days)
    longest = max([*cycles.values(), DEFAULT_CYCLE])
    since = now - window - 2 * longest
    query = """
        SELECT l.source, o.observed_at, nxt.observed_at AS back_at
        FROM price_observations o
        JOIN listings l ON l.id = o.listing_id
        LEFT JOIN LATERAL (
            SELECT n.observed_at FROM price_observations n
            WHERE n.listing_id = o.listing_id AND n.observed_at > o.observed_at
            ORDER BY n.observed_at LIMIT 1
        ) nxt ON true
        WHERE NOT o.available AND o.observed_at >= :since
          AND (CAST(:source AS text) IS NULL OR l.source = :source)
    """
    out: dict[str, dict] = defaultdict(
        lambda: {"judged": 0, "back_within": 0, "too_recent": 0, "judge_days": None}
    )
    for row in (await session.execute(text(query), {"since": since, "source": source})).all():
        horizon = 2 * cycles.get(row.source, DEFAULT_CYCLE)
        entry = out[row.source]
        entry["judge_days"] = round(horizon.total_seconds() / 86400, 1)
        judge_until = now - horizon
        if row.observed_at > judge_until:
            if row.observed_at >= now - window:
                entry["too_recent"] += 1
            continue
        if row.observed_at < judge_until - window:
            continue
        entry["judged"] += 1
        if row.back_at is not None and row.back_at - row.observed_at <= horizon:
            entry["back_within"] += 1
    return {src: e for src, e in out.items() if e["judged"] or e["too_recent"]}


async def segments(session, since: datetime, source: str | None, exclude: list[str]) -> list[dict]:
    """§0's table: change share by price band, stock state and multi-supplier."""
    query = """
        WITH base AS (
            SELECT DISTINCT ON (o.listing_id) o.listing_id, o.price, o.currency,
                   o.stock_signal
            FROM price_observations o
            WHERE o.observed_at < :since
            ORDER BY o.listing_id, o.observed_at DESC
        ),
        moved AS (
            SELECT o.listing_id,
                   bool_or(o.price IS DISTINCT FROM b.price OR o.currency <> b.currency)
                       AS price_moved,
                   bool_or(o.stock_signal <> b.stock_signal) AS stock_moved
            FROM price_observations o JOIN base b USING (listing_id)
            WHERE o.observed_at >= :since AND o.available
            GROUP BY o.listing_id
        ),
        multi AS (
            SELECT product_id FROM listings
            WHERE product_id IS NOT NULL AND status = 'ACTIVE'
            GROUP BY product_id HAVING count(DISTINCT supplier_id) > 1
        )
        SELECT b.price, b.stock_signal, (m.product_id IS NOT NULL) AS multi,
               coalesce(mv.price_moved, false) AS price_moved,
               coalesce(mv.stock_moved, false) AS stock_moved
        FROM base b
        JOIN listings l ON l.id = b.listing_id
        LEFT JOIN multi m ON m.product_id = l.product_id
        LEFT JOIN moved mv ON mv.listing_id = b.listing_id
        WHERE l.last_verified_at >= :since
          AND (CAST(:source AS text) IS NULL OR l.source = :source)
          AND NOT (l.source = ANY(:exclude))
    """
    rows = (
        await session.execute(
            text(query), {"since": since, "source": source, "exclude": list(exclude)}
        )
    ).all()

    def band(price) -> str:
        if price is None:
            return "no price"
        for name, lo, hi in PRICE_BANDS[1:]:
            if price >= lo and (hi is None or price < hi):
                return name
        return "no price"

    groups: dict[str, list] = defaultdict(list)
    for row in rows:
        groups[f"price {band(row.price)}"].append(row)
        stock = "in stock" if row.stock_signal == "IN_STOCK" else "not in stock"
        groups[f"{stock} at baseline"].append(row)
        groups["multi-supplier" if row.multi else "single supplier"].append(row)
    all_moved = sum(1 for r in rows if r.price_moved or r.stock_moved)
    order = [f"price {name}" for name, *_ in PRICE_BANDS] + [
        "in stock at baseline",
        "not in stock at baseline",
        "multi-supplier",
        "single supplier",
    ]
    out = []
    for name in order:
        items = groups.get(name, [])
        if not items:
            continue
        either = sum(1 for r in items if r.price_moved or r.stock_moved)
        out.append(
            {
                "segment": name,
                "n": len(items),
                "price": sum(1 for r in items if r.price_moved),
                "stock": sum(1 for r in items if r.stock_moved),
                "either": either,
                "share_of_changes": either / all_moved if all_moved else None,
            }
        )
    return out


def validators(runs: list, window_start: datetime) -> dict[str, Counter]:
    """T11: 2xx responses and validator counts per source over the window (`stats.validators`)."""
    out: dict[str, Counter] = defaultdict(Counter)
    for row in runs:
        if row.started_at < window_start:
            continue
        for counts in ((row.stats or {}).get("validators") or {}).values():
            if isinstance(counts, dict):
                out[row.source].update({k: v for k, v in counts.items() if isinstance(v, int)})
    return dict(out)


def category_churn(runs: list, window_start: datetime) -> dict[str, Counter]:
    """D4: category set / moved / cleared on stored listings per source (`stats.categories`)."""
    out: dict[str, Counter] = defaultdict(Counter)
    for row in runs:
        moved = (row.stats or {}).get("categories")
        if row.started_at >= window_start and isinstance(moved, dict):
            out[row.source]["runs"] += 1
            out[row.source].update({k: v for k, v in moved.items() if isinstance(v, int)})
    return dict(out)


async def collect(
    session, *, days: int = 14, source: str | None = None, exclude: list[str] | None = None
) -> dict:
    """Every figure the report prints, as data (the tests read this)."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    # Runs further back than the window, so the last completed cycle is found
    # even when it closed before the window opened.
    runs = await _runs(session, now - timedelta(days=max(days, 60)), source)
    m1 = requests_and_cycles(runs, since, now)
    # The last completed cycle's length: what "within two cycles" means now.
    cycle_lengths = {
        src: timedelta(days=entry["cycle_days"][-1])
        for src, entry in m1.items()
        if entry["cycle_days"] and entry["cycle_days"][-1] > 0
    }
    # The report also runs against a database older than the check log (to
    # take a baseline before the migration is deployed): those parts are empty.
    has_log = await _has_column(session, "listings", "last_checked_at")
    found, delays = await changes(session, since, source, has_log=has_log)
    return {
        "days": days,
        "has_check_log": has_log,
        "since": since,
        "requests": m1,
        "staleness": await staleness(session, source),
        "check_log": await check_log(session, source) if has_log else {},
        "changes": found,
        "detection_delay": delays,
        "false_archivals": await false_archivals(session, now, days, source, cycle_lengths),
        "segments": await segments(session, since, source, exclude or []),
        "validators": validators(runs, since),
        "categories": category_churn(runs, since),
    }


def render(data: dict) -> None:
    days = data["days"]
    sources = sorted(set(data["requests"]) | set(data["staleness"]) | set(data["check_log"]))

    _header(f"M1 REQUESTS (last {days}d, limit= runs excluded)")
    print(
        f"  {DIM}{'source':22s} {'per day':>8} {'max day':>8} {'window':>8} {'last cycle':>11}{RESET}"
    )
    for src in sources:
        e = data["requests"].get(src)
        if not e:
            continue
        cyc = _count(e["cycle_requests"], e["cycle_requests_partial"])
        window = _count(e["requests_window"], e["requests_window_partial"])
        print(
            f"  {src:22s} {e['requests_per_day']:>8.1f} {e['requests_max_day']:>8}"
            f" {window:>8} {cyc:>11}"
        )
    print(
        f"  {DIM}>=N: some runs recorded no count (older than the counting, or cut off);"
        f" '-': none did{RESET}"
    )

    _header("M2 COVERAGE (cycle length; age of last_verified_at over active listings)")
    print(
        f"  {DIM}{'source':22s} {'active':>7} {'p50':>7} {'p90':>7} {'p99':>7}  last cycles{RESET}"
    )
    for src in sources:
        s = data["staleness"].get(src, {})
        cycles = data["requests"].get(src, {}).get("cycle_days") or []
        print(
            f"  {src:22s} {s.get('active', 0):>7} {_days(s.get('p50')):>7}"
            f" {_days(s.get('p90')):>7} {_days(s.get('p99')):>7}"
            f"  {', '.join(f'{c}d' for c in cycles) or '-'}"
        )

    _header(f"M3 CHANGES PER 1,000 REQUESTS (last {days}d) and the check log")
    print(
        f"  {DIM}{'source':22s} {'changes':>8} {'requests':>9} {'per 1k':>7}  by lane"
        f"   {'checked':>8} {'checks':>7} {'changed':>8} {'d/change':>9}{RESET}"
    )
    for src in sources:
        by_via = data["changes"].get(src, Counter())
        total = sum(by_via.values())
        m1 = data["requests"].get(src, {})
        requests = m1.get("requests_window", 0)
        per_k = f"{1000 * total / requests:.0f}" if requests else "-"
        if requests and m1.get("requests_window_partial"):
            per_k = f"<={per_k}"  # some requests went uncounted, so fewer per 1k
        requests = _count(requests, bool(m1.get("requests_window_partial")))
        lanes = ", ".join(f"{k} {v}" for k, v in sorted(by_via.items())) or "-"
        log = data["check_log"].get(src, {})
        dbc = log.get("days_between_changes")
        print(
            f"  {src:22s} {total:>8} {requests:>9} {per_k:>7}  {lanes:8s}"
            f" {log.get('listings', 0):>8} {log.get('checks', 0):>7} {log.get('changes', 0):>8}"
            f" {('-' if dbc is None else f'{dbc:.0f}'):>9}"
        )

    if not data.get("has_check_log", True):
        print(f"  {DIM}this database has no check log yet (migration e64070b70b6d){RESET}")

    _header(f"M5 DETECTION DELAY (change found minus the previous read, {days}d)")
    print(f"  {DIM}{'source':22s} {'changes':>8} {'p50':>7} {'p90':>7}{RESET}")
    if not data["detection_delay"]:
        print(f"  {DIM}no change in the window was found after a counted read yet{RESET}")
    for src, d in sorted(data["detection_delay"].items()):
        print(f"  {src:22s} {d['n']:>8} {_days(d['p50']):>7} {_days(d['p90']):>7}")

    _header("M6 FALSE ARCHIVALS (back within two cycles of being archived)")
    print(
        f"  {DIM}{'source':22s} {'judged':>7} {'back':>6} {'share':>7}"
        f" {'too recent':>11}  two cycles{RESET}"
    )
    if not data["false_archivals"]:
        print(f"  {DIM}nothing archived to judge{RESET}")
    for src, e in sorted(data["false_archivals"].items()):
        print(
            f"  {src:22s} {e['judged']:>7} {e['back_within']:>6}"
            f" {_pct(e['back_within'], e['judged']):>7} {e['too_recent']:>11}"
            f"  {_days(e['judge_days'])}"
        )
    print(
        f"  {DIM}judged: archived in the {days}d before two cycles ago;"
        f" too recent: archived in the last {days}d, under two cycles ago{RESET}"
    )

    _header(f"SEGMENTS (re-read in the last {days}d, against the row in force before it)")
    print(
        f"  {DIM}{'segment':26s} {'n':>7} {'price':>7} {'stock':>7} {'either':>7}"
        f" {'share of changes':>17}{RESET}"
    )
    if not data["segments"]:
        print(f"  {DIM}no listing re-read in the window had a baseline row{RESET}")
    for seg in data["segments"]:
        share = seg["share_of_changes"]
        print(
            f"  {seg['segment']:26s} {seg['n']:>7} {_pct(seg['price'], seg['n']):>7}"
            f" {_pct(seg['stock'], seg['n']):>7} {_pct(seg['either'], seg['n']):>7}"
            f" {('-' if share is None else f'{100 * share:.0f}%'):>17}"
        )

    _header(f"VALIDATORS (T11; 2xx responses in the last {days}d)")
    if not data["validators"]:
        print(f"  {DIM}no run has recorded validators yet{RESET}")
    for src, c in sorted(data["validators"].items()):
        n = c.get("responses", 0)
        print(
            f"  {src:22s} {n:>6} responses  ETag {_pct(c.get('etag', 0), n):>6}"
            f" (weak {c.get('etag_weak', 0)})  Last-Modified {_pct(c.get('last_modified', 0), n):>6}"
        )

    _header(f"CATEGORY CHURN (D4; stored listings' category changed by a sweep, {days}d)")
    if not data["categories"]:
        print(f"  {DIM}no run has recorded category changes yet{RESET}")
    for src, c in sorted(data["categories"].items()):
        print(
            f"  {src:22s} {c.get('runs', 0):>4} runs  moved {c.get('moved', 0):>5}"
            f"  set {c.get('set', 0):>5}  cleared {c.get('cleared', 0):>5}"
        )
    print()


async def main() -> None:
    parser = argparse.ArgumentParser(description="makhzan crawler freshness report")
    parser.add_argument("--source", help="limit to one source id")
    parser.add_argument("--days", type=int, default=14, help="window in days (default 14)")
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="leave a source out of the segment table (repeatable)",
    )
    args = parser.parse_args()

    async with SessionLocal() as session:
        # Read-only by construction, whichever database this points at.
        await session.execute(text("SET TRANSACTION READ ONLY"))
        try:
            data = await collect(session, days=args.days, source=args.source, exclude=args.exclude)
        finally:
            await session.rollback()
    render(data)


if __name__ == "__main__":
    asyncio.run(main())
