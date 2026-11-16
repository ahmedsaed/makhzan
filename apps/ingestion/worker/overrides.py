"""Grouping overrides by hand: a person's ruling that two listings are, or are not, one product.

    python -m worker.overrides                       # list every override, newest first
    python -m worker.overrides list [--limit N]
    python -m worker.overrides add LISTING LISTING --kind never|must [--forced] --note "why"
    python -m worker.overrides remove ID [ID ...]

`./makhzan overrides ...` runs this in the production worker, and `make
overrides ARGS="..."` against the local database. Accepting a grouping report
(`./makhzan reports accept`) writes them too; those cite their report.

A ruling takes effect at the next regroup, which every crawl queues, or at
once with `./makhzan reindex` (`worker.regroup`). What each kind does is
`makhzan_schemas.overrides`; a pair has one ruling, so to change one, remove
it and add the other. Every product a ruling changes cites it in
`product_events`.
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

from worker.reports import printable, ruling_line, who


def _describe_listing(listing: Listing | None, listing_id: uuid.UUID) -> str:
    if listing is None:
        return f"    {listing_id} (gone)"
    shop = listing.supplier.name if listing.supplier else listing.source
    title = listing.title_en or listing.title_ar or "(untitled)"
    return f"    {listing.id} {title} | {shop} | {listing.status} | product {listing.product_id}"


async def _list(limit: int) -> int:
    async with SessionLocal() as session:
        rows = list(
            await session.scalars(
                select(GroupingOverride).order_by(GroupingOverride.id.desc()).limit(limit)
            )
        )
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
        origin = f"report R-{row.report_id}" if row.report_id else "manual"
        lines = [
            f"#{row.id} {row.kind}{' forced' if row.forced else ''}  {origin}  "
            f"{row.created_at:%Y-%m-%d %H:%M} UTC by {row.created_by}",
            _describe_listing(listings.get(row.listing_a), row.listing_a),
            _describe_listing(listings.get(row.listing_b), row.listing_b),
        ]
        if row.note:
            lines.append(f"    note: {row.note}")
        print(printable("\n".join(lines)))
    return 0


async def _add(a: uuid.UUID, b: uuid.UUID, kind: str, forced: bool, note: str, by: str) -> int:
    async with SessionLocal() as session:
        found = set(await session.scalars(select(Listing.id).where(Listing.id.in_([a, b]))))
        missing = [str(x) for x in (a, b) if x not in found]
        if missing:
            print(f"No listing {', '.join(missing)}.", file=sys.stderr)
            return 1
        added = await rulings.add(session, a, b, kind, forced=forced, note=note, created_by=by)
        await session.commit()
    print(ruling_line(added))
    return 1 if added.outcome == "conflict" else 0


async def _remove(ids: Sequence[int]) -> int:
    missing = 0
    async with SessionLocal() as session:
        for override_id in ids:
            row = await rulings.remove(session, override_id)
            if row is None:
                print(f"No override #{override_id}.", file=sys.stderr)
                missing += 1
            else:
                print(f"Removed #{override_id} {row.kind} (applies at the next regroup).")
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
    listing = sub.add_parser("list", help="every override, newest first")
    listing.add_argument("--limit", type=int, default=100)
    add = sub.add_parser("add", help="rule that two listings are never, or must be, one product")
    add.add_argument("a", type=uuid.UUID, help="a listing id")
    add.add_argument("b", type=uuid.UUID, help="the other listing id")
    add.add_argument("--kind", required=True, choices=("never", "must"))
    add.add_argument(
        "--forced", action="store_true", help="must only: past the value, form and price vetoes"
    )
    add.add_argument("--note", required=True, help="why: kept with the ruling")
    add.add_argument("--by", help="who is ruling (default: login)")
    remove = sub.add_parser("remove", help="delete one or more overrides")
    remove.add_argument("ids", type=_override_id, nargs="+")
    return parser


async def run(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command in (None, "list"):
        return await _list(getattr(args, "limit", 100))
    if args.command == "remove":
        return await _remove(args.ids)
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
