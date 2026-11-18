"""Grouping overrides by hand: a person's ruling that two listings are, or are not, one product.

    python -m worker.overrides                       # standing overrides, newest first
    python -m worker.overrides list [--limit N] [--all]   # --all: removed ones too
    python -m worker.overrides add LISTING LISTING --kind never|must [--forced] --note "why"
    python -m worker.overrides remove ID [ID ...] [--note "why"]   # keeps the row, marked removed

`./makhzan overrides ...` runs this in the production worker, and `make
overrides ARGS="..."` against the local database. Accepting a grouping report
(`./makhzan reports accept`) writes them too; those cite their report.

A ruling takes effect at the next regroup, which every crawl queues, or at
once with `./makhzan reindex` (`worker.regroup`). What each kind does is
`makhzan_schemas.overrides`; a pair has one standing ruling, so to change
one, remove it and add the other (a new row; the removed one stays, with who
removed it and when). Every product a ruling changes cites it in
`product_events`, and so does the regroup that undoes a removed one.

The list shows what the last regroup found for each ruling: in effect,
BLOCKED (and by which listing and veto: an existing product wins over a
ruling it contradicts, forced or not), inactive (a listing is archived) or
removed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from collections.abc import Sequence

from makhzan_schemas import overrides as rulings
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.models import GroupingOverride, Listing
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from worker.reports import override_lines, printable, ruling_line, who


def _describe_listing(listing: Listing | None, listing_id: uuid.UUID) -> str:
    if listing is None:
        return f"    {listing_id} (gone)"
    shop = listing.supplier.name if listing.supplier else listing.source
    title = listing.title_en or listing.title_ar or "(untitled)"
    return f"    {listing.id} {title} | {shop} | {listing.status} | product {listing.product_id}"


async def _list(limit: int, everything: bool = False) -> int:
    async with SessionLocal() as session:
        query = select(GroupingOverride).order_by(GroupingOverride.id.desc()).limit(limit)
        if not everything:
            query = query.where(GroupingOverride.removed_at.is_(None))
        rows = list(await session.scalars(query))
        ids = {i for row in rows for i in (row.listing_a, row.listing_b)}
        listings = {
            listing.id: listing
            for listing in await session.scalars(
                select(Listing).where(Listing.id.in_(ids)).options(selectinload(Listing.supplier))
            )
        }
    if not rows:
        print("No grouping overrides.")
        return 0
    for row in rows:
        lines = [
            *override_lines(row),
            _describe_listing(listings.get(row.listing_a), row.listing_a),
            _describe_listing(listings.get(row.listing_b), row.listing_b),
        ]
        if row.note:
            lines.append(f"    note: {row.note}")
        print(printable("\n".join(lines)))
    return 0


class OverrideRefused(ValueError):
    """A ruling that cannot be recorded: a listing is missing, or it could never act."""


async def add_override(
    session, a: uuid.UUID, b: uuid.UUID, kind: str, *, forced: bool, note: str, by: str
) -> rulings.Added:
    """Record one ruling by hand (flushed, not committed); what `overrides add` does.

    Raises `OverrideRefused` for a listing that does not exist, or a must_merge
    between two listings of one shop, which never merges, forced or not
    (grouping._Rulings): it would sit in the table and never act. A pair with
    the other ruling standing comes back as `conflict`, nothing written.
    """
    if a == b:
        raise OverrideRefused("an override is about two different listings")
    if not note.strip():
        raise OverrideRefused("a note must say why")
    if forced and kind != rulings.MUST:
        raise OverrideRefused("only a must_merge can be forced")
    shops = dict(
        (
            await session.execute(
                select(Listing.id, Listing.supplier_id).where(Listing.id.in_([a, b]))
            )
        ).all()
    )
    missing = [str(x) for x in (a, b) if x not in shops]
    if missing:
        raise OverrideRefused(f"No listing {', '.join(missing)}.")
    if kind == rulings.MUST and shops[a] == shops[b]:
        raise OverrideRefused(
            "Both listings are from the same shop, which never merges: a must_merge "
            "between them would do nothing. Not recorded."
        )
    return await rulings.add(session, a, b, kind, forced=forced, note=note, created_by=by)


async def _add(a: uuid.UUID, b: uuid.UUID, kind: str, forced: bool, note: str, by: str) -> int:
    async with SessionLocal() as session:
        try:
            added = await add_override(session, a, b, kind, forced=forced, note=note, by=by)
        except OverrideRefused as refused:
            print(str(refused), file=sys.stderr)
            return 1
        await session.commit()
    print(ruling_line(added))
    return 1 if added.outcome == "conflict" else 0


async def _remove(ids: Sequence[int], by: str, note: str | None = None) -> int:
    missing = 0
    async with SessionLocal() as session:
        for override_id in ids:
            row = await rulings.remove(session, override_id, removed_by=by, note=note)
            if row is None:
                print(f"No override #{override_id}.", file=sys.stderr)
                missing += 1
            else:
                print(
                    f"Removed #{override_id} {row.kind} by {row.removed_by} "
                    "(row kept; applies at the next regroup)."
                )
        await session.commit()
    return 1 if missing else 0


def _override_id(value: str) -> int:
    value = value.strip().removeprefix("#")
    if not value.isdigit():
        raise argparse.ArgumentTypeError(f"not an override id: {value!r}")
    return int(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="overrides", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command")
    listing = sub.add_parser("list", help="standing overrides and their status, newest first")
    listing.add_argument("--limit", type=int, default=100)
    listing.add_argument("--all", action="store_true", help="removed overrides too")
    add = sub.add_parser("add", help="rule that two listings are never, or must be, one product")
    add.add_argument("a", type=uuid.UUID, help="a listing id")
    add.add_argument("b", type=uuid.UUID, help="the other listing id")
    add.add_argument("--kind", required=True, choices=("never", "must"))
    add.add_argument(
        "--forced", action="store_true", help="must only: past the value, form and price vetoes"
    )
    add.add_argument("--note", required=True, help="why: kept with the ruling")
    add.add_argument("--by", help="who is ruling (default: login)")
    remove = sub.add_parser("remove", help="withdraw one or more overrides (rows are kept)")
    remove.add_argument("ids", type=_override_id, nargs="+")
    remove.add_argument("--by", help="who is removing (default: login)")
    remove.add_argument("--note", help="why: kept with the removed ruling")
    return parser


async def run(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command in (None, "list"):
        return await _list(getattr(args, "limit", 100), getattr(args, "all", False))
    if args.command == "remove":
        return await _remove(args.ids, who(args.by), args.note)
    kind = rulings.NEVER if args.kind == "never" else rulings.MUST
    if args.forced and kind != rulings.MUST:
        parser.error("--forced goes with --kind must")
    if not args.note.strip():
        parser.error("--note must say why")
    if args.a == args.b:
        parser.error("an override is about two different listings")
    return await _add(args.a, args.b, kind, args.forced, args.note, who(args.by))


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
