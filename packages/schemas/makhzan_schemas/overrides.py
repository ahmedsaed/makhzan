"""Grouping overrides: a person's ruling that two listings are, or are not, one product.

Rows live in `grouping_overrides` (`models.GroupingOverride`), keyed by the
unordered listing pair. Two kinds:

- `never_merge`: no product may hold both. The regroup treats it as a veto
  between those two listings wherever it checks vetoes.
- `must_merge`: evidence that admits the two to one product without title
  agreement or a shared identifier. Vetoes still apply unless `forced`; the
  same shop never merges, forced or not.

Who reads it: the regroup (`grouping.rebuild_products`, through
`load_overrides`) and, later, AI matching (docs/ai/plan.md), which must take
the same rulings as fact rather than ask a model again. Who writes it:
`accept_report` (`./makhzan reports accept`) and `add` (`./makhzan overrides
add`, a note required). A ruling takes effect at the next regroup.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from makhzan_schemas.enums import ListingStatus
from makhzan_schemas.models import GroupingOverride, Listing, Report

NEVER = "never_merge"
MUST = "must_merge"
KINDS = (NEVER, MUST)
SOURCES = ("report", "manual")

Pair = tuple[uuid.UUID, uuid.UUID]


def pair(a: uuid.UUID, b: uuid.UUID) -> Pair:
    """The pair as stored: the smaller id first (uuid order is Postgres's too)."""
    if a == b:
        raise ValueError("an override is about two different listings")
    return (a, b) if a < b else (b, a)


@dataclass(frozen=True)
class Overrides:
    """Every ruling, as sets of ordered pairs: what grouping and AI matching read.

    `forced` is a subset of `must`. `ids` gives each pair's row id, so an effect
    can cite the ruling behind it.
    """

    never: frozenset[Pair] = frozenset()
    must: frozenset[Pair] = frozenset()
    forced: frozenset[Pair] = frozenset()
    ids: dict[Pair, int] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.never or self.must)

    def kind(self, a: uuid.UUID, b: uuid.UUID) -> str | None:
        """`never_merge`, `must_merge` or None for two listings, in either order."""
        if a == b:
            return None
        key = pair(a, b)
        if key in self.never:
            return NEVER
        if key in self.must:
            return MUST
        return None

    def is_forced(self, a: uuid.UUID, b: uuid.UUID) -> bool:
        return a != b and pair(a, b) in self.forced

    @classmethod
    def of(cls, rows: Iterable[GroupingOverride]) -> Overrides:
        never: set[Pair] = set()
        must: set[Pair] = set()
        forced: set[Pair] = set()
        ids: dict[Pair, int] = {}
        for row in rows:
            key = pair(row.listing_a, row.listing_b)
            (never if row.kind == NEVER else must).add(key)
            if row.kind == MUST and row.forced:
                forced.add(key)
            ids[key] = row.id
        return cls(frozenset(never), frozenset(must), frozenset(forced), ids)


async def load_overrides(session: AsyncSession) -> Overrides:
    """Every ruling in the table, for grouping now and AI decisions later."""
    rows = await session.scalars(select(GroupingOverride).order_by(GroupingOverride.id))
    return Overrides.of(rows)


@dataclass
class Added:
    """What `add` did with one pair: `created`, `exists` (the same ruling was
    already there) or `conflict` (the pair has the other ruling; nothing
    written, so a contradicting ruling is never made by accident)."""

    outcome: str
    row: GroupingOverride


async def add(
    session: AsyncSession,
    a: uuid.UUID,
    b: uuid.UUID,
    kind: str,
    *,
    created_by: str,
    forced: bool = False,
    report_id: int | None = None,
    note: str | None = None,
    now: datetime | None = None,
) -> Added:
    """Record one ruling (flushed, not committed).

    One ruling a pair: asking for the ruling already there changes nothing;
    asking for the other kind is a conflict and writes nothing, so the person
    removes the old one first, deliberately.
    """
    if kind not in KINDS:
        raise ValueError(f"an override is {' or '.join(KINDS)}, not {kind!r}")
    if forced and kind != MUST:
        raise ValueError("only a must_merge can be forced")
    note = (note or "").strip() or None
    if report_id is None and note is None:
        raise ValueError("a manual override needs a note saying why")
    if not created_by.strip():
        raise ValueError("say who made the override")
    first, second = pair(a, b)
    existing = await session.scalar(
        select(GroupingOverride).where(
            GroupingOverride.listing_a == first, GroupingOverride.listing_b == second
        )
    )
    if existing is not None:
        same = existing.kind == kind and existing.forced == forced
        return Added("exists" if same else "conflict", existing)
    row = GroupingOverride(
        listing_a=first,
        listing_b=second,
        kind=kind,
        forced=forced,
        source="report" if report_id is not None else "manual",
        report_id=report_id,
        note=note,
        created_by=created_by.strip()[:100],
    )
    if now is not None:
        row.created_at = now
    session.add(row)
    await session.flush()
    return Added("created", row)


async def remove(session: AsyncSession, override_id: int) -> GroupingOverride | None:
    """Delete one ruling (flushed, not committed); None if there is no such row."""
    row = await session.get(GroupingOverride, override_id)
    if row is not None:
        await session.delete(row)
        await session.flush()
    return row


def _snapshot_ids(listings: list[dict], *, ticked: bool | None = None) -> list[uuid.UUID]:
    out = []
    for listing in listings:
        if ticked is not None and bool(listing.get("ticked")) != ticked:
            continue
        try:
            out.append(uuid.UUID(str(listing.get("id"))))
        except ValueError:
            continue
    return out


class ReportRefused(ValueError):
    """An accepted report that cannot stand for any ruling that would act."""


async def _ranked(session: AsyncSession, ids: list[uuid.UUID]) -> list:
    """A product's listings, those most likely to stay first: active, then the
    earliest seen, then the natural key (source, external id)."""
    if not ids:
        return []
    rows = (
        await session.execute(
            select(
                Listing.id,
                Listing.supplier_id,
                Listing.status,
                Listing.first_seen_at,
                Listing.source,
                Listing.external_id,
            ).where(Listing.id.in_(ids))
        )
    ).all()
    return sorted(
        rows,
        key=lambda r: (
            r.status != ListingStatus.ACTIVE,
            r.first_seen_at.timestamp() if r.first_seen_at else float("inf"),
            r.source,
            r.external_id or "",
            str(r.id),
        ),
    )


def _representatives(mine: list, theirs: list) -> Pair | None:
    """One listing of each product, from different shops (the same shop never
    merges, so a same-shop must_merge would never act): the pair whose worse
    rank is best, then the better rank, then this product's rank."""
    best = None
    for i, a in enumerate(mine):
        for j, b in enumerate(theirs):
            if a.supplier_id == b.supplier_id or a.id == b.id:
                continue
            rank = (max(i, j), i + j, i)
            if best is None or rank < best[0]:
                best = (rank, pair(a.id, b.id))
    return best[1] if best else None


async def report_pairs(session: AsyncSession, report: Report) -> list[tuple[Pair, str]]:
    """The rulings an accepted report stands for, as (pair, kind).

    Read from the report's snapshot: what the visitor saw and ticked, not what
    the product holds now, which a regroup may have changed since. Listings
    that no longer exist are left out.

    - `offers_not_same`: never_merge between every ticked offer and every
      offer left unticked. Nothing is said about ticked against ticked.
    - `same_as_other`: one must_merge, between a representative listing of
      each product, from two different shops (`_representatives`; refused
      with `ReportRefused` when there is no such pair). One pair is enough: admission is
      single-link (a cluster takes a candidate on its best-matching member)
      while every veto is checked against every member, so it joins the two
      products and still refuses any member that contradicts the other. Every
      pair would also assert that each product's present members all belong,
      binding in any wrong member it held when the report was sent.
    - any other reason: none.
    """
    snap = report.snapshot or {}
    product = snap.get("product") or {}
    listings = product.get("listings") or []
    pairs: list[tuple[Pair, str]] = []
    if report.reason == "offers_not_same":
        ticked = _snapshot_ids(listings, ticked=True)
        unticked = _snapshot_ids(listings, ticked=False)
        existing = set(
            await session.scalars(select(Listing.id).where(Listing.id.in_(ticked + unticked)))
        )
        for a in ticked:
            for b in unticked:
                if a in existing and b in existing and a != b:
                    pairs.append((pair(a, b), NEVER))
    elif report.reason == "same_as_other":
        other = snap.get("other_product") or {}
        joined = _representatives(
            await _ranked(session, _snapshot_ids(listings)),
            await _ranked(session, _snapshot_ids(other.get("listings") or [])),
        )
        if joined is None:
            raise ReportRefused(
                "no listing of one product is from a different shop than a listing of the "
                "other (or none exists any more): the same shop never merges, so no ruling "
                "could join them"
            )
        pairs.append((joined, MUST))
    return sorted(set(pairs), key=lambda p: (str(p[0][0]), str(p[0][1])))


async def accept_report(
    session: AsyncSession,
    report: Report,
    *,
    created_by: str,
    pairs: list[tuple[Pair, str]] | None = None,
) -> list[Added]:
    """Write the rulings an accepted report stands for (flushed, not committed).

    `pairs` are `report_pairs`' answer when the caller already has it; that
    raises `ReportRefused` for a report no ruling could act on.
    """
    results = []
    if pairs is None:
        pairs = await report_pairs(session, report)
    for (a, b), kind in pairs:
        results.append(await add(session, a, b, kind, created_by=created_by, report_id=report.id))
    return results


async def withdraw_report(session: AsyncSession, report_id: int) -> int:
    """Delete the rulings a report made (flushed, not committed): how a report
    accepted by mistake, then rejected, stops acting. Returns how many."""
    result = await session.execute(
        delete(GroupingOverride).where(GroupingOverride.report_id == report_id)
    )
    await session.flush()
    return result.rowcount or 0
