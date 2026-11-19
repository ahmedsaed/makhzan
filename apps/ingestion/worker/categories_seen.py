"""Every shop category a listing appeared under, per cycle, and a report on them.

    python -m worker.categories_seen [--source ID] [--conflicts-only]

`./makhzan categories-seen ...` runs it in the production worker, and `make
categories-seen ARGS="..."` against the local database. Read-only.

**Record only.** A shop browsed by category partitions (the Odoo shop, the Wix
shop) says which category a product is in only by listing it on that
category's pages. A product filed under several is seen once per partition, and
the pipeline assigns whichever partition was swept last, so a product in two
leaves that map differently flips category from cycle to cycle. Nothing here
changes that: the pipeline still assigns the category exactly as before. What
this adds is the evidence, so a person can decide what multi-category products
should be filed under.

Each category partition's upsert adds the shop's own name for the partition
(`source_categories(raw)`, mapped, unmapped or ignored alike) to the listing's
`attributes.categories_seen`::

    {"2026-11-01T06:00:00+00:00": ["cat-a", "cat-b"],   # the previous cycle
     "2026-11-08T06:00:00+00:00": ["cat-a"]}            # the cycle in flight

keyed by the cycle's `cycle_started_at`, the same instant the run that
completes the cycle records as `stats.cycle.cycle_started_at`. Only the newest
two keys are kept: the cycle in flight and the one before it, which is the last
completed cycle once the in-flight one has started. A pass that carries no
category (`knows_category` False, the whole-shop pass) records nothing, nor do
`limit=` runs, the archive confirmation or re-checks: only a full run's sweep of
a category partition. The list-page upsert rebuilds attributes from the card, so
`carry` lays the stored value back on (as `worker.details.carry_details` does).

Nothing reads the key but this report: the AI prompt (`makhzan_schemas.ai.prompt`)
and the API read named attribute keys only.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime
from itertools import combinations

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.domains.crosswalks import load_crosswalk, normalize_category_name
from makhzan_schemas.enums import ListingStatus
from makhzan_schemas.models import Category, IngestionRun, Listing, Source
from sqlalchemy import func, select

KEY = "categories_seen"

#: The cycle in flight and the one before it.
KEEP_CYCLES = 2


def _when(stamp: object) -> datetime | None:
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


def record(attributes: dict | None, cycle: str, names: Iterable[str]) -> dict:
    """`attributes` with `names` added under `cycle`, the oldest cycles dropped.

    Returns a new dict (a JSONB column only notices a new value). Names keep
    the order first seen; the kept cycles are the newest `KEEP_CYCLES` by date.
    """
    attributes = dict(attributes or {})
    stored = attributes.get(KEY)
    seen: dict[str, list[str]] = {
        stamp: list(listed)
        for stamp, listed in (stored.items() if isinstance(stored, dict) else ())
        if _when(stamp) is not None and isinstance(listed, list)
    }
    listed = seen.setdefault(cycle, [])
    for name in names:
        if name and name not in listed:
            listed.append(name)
    newest = sorted(seen, key=_when, reverse=True)[:KEEP_CYCLES]
    attributes[KEY] = {stamp: seen[stamp] for stamp in sorted(newest, key=_when)}
    return attributes


def carry(stored: object, fresh: dict) -> dict:
    """`fresh` attributes (from a card) with the stored row's memberships kept."""
    if isinstance(stored, dict) and KEY in stored:
        return {**fresh, KEY: stored[KEY]}
    return fresh


def in_cycle(attributes: object, cycle_started: datetime) -> list[str]:
    """The categories a listing was seen under in the cycle that began then."""
    stored = attributes.get(KEY) if isinstance(attributes, dict) else None
    for stamp, listed in (stored or {}).items():
        if _when(stamp) == cycle_started and isinstance(listed, list):
            return listed
    return []


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #

UNMAPPED = "unmapped"
IGNORED = "ignored"


def _crosswalk(config: dict | None) -> tuple[dict[str, str], set[str], str | None]:
    """(folded name -> "domain:slug", folded ignored names, why there is none)."""
    name = (config or {}).get("crosswalk")
    if not name:
        return {}, set(), "no crosswalk named in the source's config"
    try:
        loaded = load_crosswalk(name)
    except (OSError, ValueError) as exc:
        return {}, set(), f"crosswalk {name!r} could not be loaded: {exc}"
    mapped = {
        normalize_category_name(source_name): f"{domain}:{slug}"
        for source_name, (domain, slug) in loaded.categories.items()
    }
    return mapped, {normalize_category_name(n) for n in loaded.ignore}, None


async def _last_cycle(session, source: str) -> dict | None:
    """The newest `stats.cycle` a run of `source` recorded, if any."""
    cycle = await session.scalar(
        select(IngestionRun.stats["cycle"])
        .where(IngestionRun.source == source, IngestionRun.stats.has_key("cycle"))
        .order_by(IngestionRun.started_at.desc())
        .limit(1)
    )
    return cycle if isinstance(cycle, dict) else None


async def _runs_without_recording(session, source: str, cycle: dict) -> int:
    """Runs that swept pages during `cycle` but recorded no memberships.

    A run marks `stats.categories_seen` when its sweep recorded them, and
    `stats.categories` whenever a full run swept pages; one with the second and
    not the first ran before recording began, so the cycle's picture is partial.
    """
    started = _when(cycle.get("cycle_started_at"))
    completed = _when(cycle.get("cycle_completed_at")) or started
    ended = func.coalesce(IngestionRun.finished_at, IngestionRun.started_at)
    return await session.scalar(
        select(func.count())
        .select_from(IngestionRun)
        .where(
            IngestionRun.source == source,
            IngestionRun.stats.has_key("categories"),
            ~IngestionRun.stats.has_key(KEY),
            IngestionRun.started_at <= completed,
            ended >= started,
        )
    )


async def collect(session, source: str) -> dict:
    """What `source`'s listings were seen under in its last completed cycle."""
    out: dict = {"source": source, "cycle": None, "why_no_crosswalk": None, "products": []}
    cycle = await _last_cycle(session, source)
    started = _when((cycle or {}).get("cycle_started_at"))
    out["cycle"] = cycle if started else None

    config = await session.scalar(select(Source.config).where(Source.source_id == source))
    mapped, ignored, out["why_no_crosswalk"] = _crosswalk(config)

    rows = (
        await session.execute(
            select(
                Listing.external_id,
                Listing.title_en,
                Listing.title_ar,
                Listing.attributes,
                Category.domain,
                Category.slug,
            )
            .outerjoin(Category, Category.id == Listing.category_id)
            .where(
                Listing.source == source,
                Listing.status == ListingStatus.ACTIVE,
                Listing.attributes.has_key(KEY),
            )
            .order_by(Listing.external_id)
        )
    ).all()
    out["recorded"] = len(rows)
    if started is None:
        return out
    out["runs_without_recording"] = await _runs_without_recording(session, source, cycle)

    out["seen_in_cycle"] = 0
    for external_id, title_en, title_ar, attributes, domain, slug in rows:
        names = in_cycle(attributes, started)
        out["seen_in_cycle"] += bool(names)
        if len(names) < 2:
            continue
        maps = []
        for name in names:
            folded = normalize_category_name(name)
            maps.append((name, mapped.get(folded) or (IGNORED if folded in ignored else UNMAPPED)))
        leaves = {target for _, target in maps if target not in (UNMAPPED, IGNORED)}
        out["products"].append(
            {
                "external_id": external_id,
                "title": title_en or title_ar or "",
                "stored": f"{domain}:{slug}" if slug else None,
                "categories": maps,
                "distinct_leaves": len(leaves),
            }
        )
    return out


def summary(report: dict) -> dict:
    products = report["products"]
    pairs: Counter = Counter()
    for product in products:
        names = sorted(name for name, _ in product["categories"])
        pairs.update(combinations(names, 2))
    return {
        "multi": len(products),
        "conflicts": sum(1 for p in products if p["distinct_leaves"] >= 2),
        "pairs": pairs.most_common(15),
    }


def format_report(report: dict, *, conflicts_only: bool = False) -> list[str]:
    source = report["source"]
    lines = [f"CATEGORIES SEEN: {source}"]
    cycle = report["cycle"]
    if cycle is None:
        lines.append(
            "  No completed cycle recorded for this source yet: nothing to report. "
            f"{report['recorded']} listings carry memberships so far."
        )
        return lines
    started = cycle["cycle_started_at"]
    lines.append(
        f"  last completed cycle: started {started}, completed {cycle.get('cycle_completed_at')}"
    )
    if not report.get("seen_in_cycle"):
        lines.append(
            "  No listing has memberships recorded for that cycle: it ran before categories "
            "were recorded. Wait for the next full cycle to complete. "
            f"({report['recorded']} listings carry memberships so far.)"
        )
        return lines
    if report.get("runs_without_recording"):
        lines.append(
            f"  PARTIAL: {report['runs_without_recording']} run(s) of that cycle swept pages "
            "before categories were recorded, so products those runs saw are missing "
            "memberships. Wait for the next full cycle for the whole picture."
        )
    if report["why_no_crosswalk"]:
        lines.append(f"  (mappings not shown: {report['why_no_crosswalk']})")

    s = summary(report)
    lines.append(
        f"  {report['seen_in_cycle']} listings seen under a category in that cycle; "
        f"{s['multi']} under two or more; {s['conflicts']} of those under two or more "
        "distinct mapped leaves"
    )
    if s["pairs"]:
        lines.append("  most common pairs:")
        lines += [f"    {count:5d}  {a}  +  {b}" for (a, b), count in s["pairs"]]

    products = sorted(report["products"], key=lambda p: (-p["distinct_leaves"], p["external_id"]))
    for heading, group in (
        (
            "in two or more distinct mapped leaves",
            [p for p in products if p["distinct_leaves"] >= 2],
        ),
        (
            "in several categories, at most one mapped leaf",
            [p for p in products if p["distinct_leaves"] < 2],
        ),
    ):
        if conflicts_only and not heading.startswith("in two"):
            continue
        if not group:
            continue
        lines.append(f"  {heading} ({len(group)}):")
        for p in group:
            lines.append(f"    {p['external_id']}  {p['title']}")
            lines.append(f"        stored today: {p['stored'] or 'uncategorized'}")
            width = max(len(name) for name, _ in p["categories"])
            lines += [f"        {name:{width}s}  -> {t}" for name, t in p["categories"]]
    return lines


async def _sources(session, source: str | None) -> list[str]:
    if source:
        return [source]
    rows = await session.execute(
        select(Listing.source).where(Listing.attributes.has_key(KEY)).distinct()
    )
    return sorted(r[0] for r in rows)


async def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="categories-seen", description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", help="one source id (default: every source with records)")
    parser.add_argument(
        "--conflicts-only",
        action="store_true",
        help="list only products under two or more distinct mapped leaves",
    )
    args = parser.parse_args(argv)
    async with SessionLocal() as session:
        sources = await _sources(session, args.source)
        if not sources:
            print(
                "No listing has recorded categories yet: no category partition has been swept "
                "since recording began."
            )
            return 0
        for i, source in enumerate(sources):
            if i:
                print()
            report = await collect(session, source)
            print("\n".join(format_report(report, conflicts_only=args.conflicts_only)))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
