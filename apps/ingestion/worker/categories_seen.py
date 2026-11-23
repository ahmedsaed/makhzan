"""Every shop category a listing appeared under, per cycle, the one it is filed
under, and a report on them.

    python -m worker.categories_seen [--source ID] [--conflicts-only]

`./makhzan categories-seen ...` runs it in the production worker, and `make
categories-seen ARGS="..."` against the local database. Read-only.

A shop browsed by category partitions (the Odoo shop, the Wix shop) says which
category a product is in only by listing it on that category's pages. A product
filed under several is seen once per partition. It used to take whichever
partition was swept last, so a product in two leaves that map differently
flipped category every cycle, and each flip re-queued its AI scores (the
category is in the prompt). The owner's rule (2026-11-23, `choose`) files it
instead under one category chosen from the **set** of names it was seen under,
deterministically and never by sweep order:

1. Names the crosswalk does not map, ignored ones included, drop out.
2. A name whose descendant also remains drops out, by the shop's own tree
   (`SourceAdapter.category_parent`) and then by our taxonomy's parent links:
   a parent-held product takes what the parent maps to, a child's mapping
   beats it.
3. (Not done: prefer the category other shops' listings of the same product
   use. That needs grouping, which runs at rebuild, and grouping reads the
   category (a listing's domain scopes its identifiers, and the category is in
   the AI prompt), so where it belongs is the owner's call. See CLAUDE.md.)
4. The crosswalk's `prefer` ranking, then the ref alphabetically.

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

The rule reads the **union** of both kept cycles (`names_seen`), so a partition
not yet swept this cycle cannot make the category flip mid-cycle. A category the
shop really removed drops out once it is absent from both: when the cycle after
the one that last saw it starts, which is one to two cycles after the removal.
It is applied by the pipeline on every sweep that knows the category, and only
for a source with `records_categories_seen`.

Nothing else reads the key: the AI prompt (`makhzan_schemas.ai.prompt`) and the
API read named attribute keys only.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime
from functools import cache
from itertools import combinations
from typing import TYPE_CHECKING

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.domains.crosswalks import load_crosswalk, normalize_category_name
from makhzan_schemas.enums import ListingStatus
from makhzan_schemas.models import Category, IngestionRun, Listing, Source
from sqlalchemy import func, select

if TYPE_CHECKING:
    from worker.sources.base import SourceAdapter

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


def names_seen(attributes: object) -> list[str]:
    """Every name the listing was seen under in the kept cycles, oldest cycle first."""
    stored = attributes.get(KEY) if isinstance(attributes, dict) else None
    if not isinstance(stored, dict):
        return []
    out: list[str] = []
    for stamp in sorted((s for s in stored if _when(s) is not None), key=_when):
        listed = stored[stamp]
        for name in listed if isinstance(listed, list) else ():
            if isinstance(name, str) and name and name not in out:
                out.append(name)
    return out


# --------------------------------------------------------------------------- #
# The rule
# --------------------------------------------------------------------------- #


@cache
def _taxonomy_parents(domain: str) -> dict[str, str]:
    from makhzan_schemas.domains import get_profile

    return {slug: parent for slug, _en, _ar, parent in get_profile(domain).taxonomy if parent}


def _taxonomy_ancestors(ref: tuple[str, str]) -> set[tuple[str, str]]:
    domain, slug = ref
    parents = _taxonomy_parents(domain)
    out: set[tuple[str, str]] = set()
    while (slug := parents.get(slug)) and (domain, slug) not in out:
        out.add((domain, slug))
    return out


def _shop_ancestors(adapter: SourceAdapter, name: str) -> set[str]:
    out: set[str] = set()
    while (name := adapter.category_parent(name)) and normalize_category_name(name) not in out:
        out.add(normalize_category_name(name))
    return out


def choose(adapter: SourceAdapter, names: Iterable[str]) -> tuple[str, str] | None:
    """The one (domain, slug) a listing seen under `names` is filed under, or None.

    The owner's rule (module docstring): unmapped and ignored names drop out;
    of a name and its ancestor, by the shop's tree and then by our taxonomy,
    the more specific stays; then the crosswalk's `prefer`, then the ref. Step 3
    (other shops' listings of the same product) is not implemented. Depends on
    the set of names only, never their order. None when no name is mapped.
    """
    mapped: dict[str, tuple[str, str]] = {}
    for name in names:
        folded = normalize_category_name(name)
        # The crosswalk refuses a name both mapped and ignored, so an ignored
        # name never maps: step 1 is "keep the mapped ones".
        if folded and folded not in mapped and (ref := adapter.category_for_name(name)):
            mapped[folded] = ref
    if not mapped:
        return None
    # Step 2, the shop's tree: drop a name one of whose descendants remains.
    held_by_descendant = set()
    for folded in mapped:
        held_by_descendant |= _shop_ancestors(adapter, folded)
    names_left = {n: r for n, r in mapped.items() if n not in held_by_descendant} or mapped
    # Step 2, our taxonomy: drop a ref one of whose descendants remains.
    refs = set(names_left.values())
    covered = set().union(*(_taxonomy_ancestors(r) for r in refs))
    refs = (refs - covered) or refs
    if len(refs) == 1:
        return next(iter(refs))
    # Step 4: the crosswalk's `prefer`, then the ref.
    preference = {normalize_category_name(n): i for i, n in enumerate(adapter.preferred_categories)}
    unranked = len(preference)

    def rank(ref: tuple[str, str]) -> tuple[int, str]:
        best = min((preference.get(n, unranked) for n, r in names_left.items() if r == ref))
        return best, f"{ref[0]}:{ref[1]}"

    return min(refs, key=rank)


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

    row = await session.scalar(select(Source).where(Source.source_id == source))
    config = row.config if row is not None else None
    mapped, ignored, out["why_no_crosswalk"] = _crosswalk(config)
    adapter, out["why_no_pick"] = _adapter(row)

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
        pick = None
        if adapter is not None:
            # What the pipeline reads: both kept cycles, not this one alone.
            chosen = choose(adapter, names_seen(attributes))
            pick = f"{chosen[0]}:{chosen[1]}" if chosen else None
        out["products"].append(
            {
                "external_id": external_id,
                "title": title_en or title_ar or "",
                "stored": f"{domain}:{slug}" if slug else None,
                "pick": pick,
                "categories": maps,
                "distinct_leaves": len(leaves),
            }
        )
    return out


def _adapter(row) -> tuple[SourceAdapter | None, str | None]:
    """The source's adapter, for the rule's pick, or why there is none."""
    from worker.sources.registry import build_adapter

    if row is None:
        return None, "no sources row"
    try:
        adapter = build_adapter(row)
    except Exception as exc:  # noqa: BLE001 — the report goes on without the pick
        return None, f"the adapter could not be built: {type(exc).__name__}: {exc}"
    if not adapter.records_categories_seen:
        return None, "the source does not file listings by the categories seen"
    return adapter, None


def summary(report: dict) -> dict:
    products = report["products"]
    pairs: Counter = Counter()
    for product in products:
        names = sorted(name for name, _ in product["categories"])
        pairs.update(combinations(names, 2))
    return {
        "multi": len(products),
        "conflicts": sum(1 for p in products if p["distinct_leaves"] >= 2),
        "pending": sum(1 for p in products if p.get("pick") and p["pick"] != p["stored"]),
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
    if report.get("why_no_pick"):
        lines.append(f"  (the rule's pick not shown: {report['why_no_pick']})")

    s = summary(report)
    lines.append(
        f"  {report['seen_in_cycle']} listings seen under a category in that cycle; "
        f"{s['multi']} under two or more; {s['conflicts']} of those under two or more "
        "distinct mapped leaves"
    )
    if s["pending"]:
        lines.append(
            f"  {s['pending']} of them stored under another category than the rule picks: "
            "the listing's next category sweep files it there"
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
            if p.get("pick") or not report.get("why_no_pick"):
                # Over both kept cycles, as the pipeline reads them.
                lines.append(f"        rule picks:   {p.get('pick') or 'nothing mapped'}")
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
