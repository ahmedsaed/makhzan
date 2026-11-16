"""Review visitors' "Report a problem" reports, on the server.

    python -m worker.reports                 # list new reports, oldest first
    python -m worker.reports list [--limit N]
    python -m worker.reports show ID         # one report, any status, in full
    python -m worker.reports accept ID [ID ...]
    python -m worker.reports reject ID [ID ...]
    python -m worker.reports purge           # erase expired emails and address hashes now

`./makhzan reports ...` runs this in the production worker, and `make reports
ARGS="..."` against the local database. There is no web page for it on
purpose: the owner decided review happens on the server.

Accepting or rejecting sets `status` and `reviewed_at`. Accepting a grouping
report also records the ruling it stands for in `grouping_overrides`
(`makhzan_schemas.overrides.report_pairs`), which the next regroup applies:
"these offers aren't the same product" keeps every ticked offer apart from
every unticked one (never_merge), "the same as another product" joins the
two products (one must_merge, between a listing of each). Rejecting a report
withdraws whatever rulings it made, so a mistaken accept can be put right.
`./makhzan overrides` lists them and makes or removes one by hand. Correcting
the page for other reasons, and turning accepted reports into labelled pairs
for matching (docs/ai/plan.md, phase G), are later steps done by hand or by a
tool not written yet. An email is erased 90 days after the report was sent,
reviewed or not.

The listing shows each report's snapshot (what the page showed when it was
sent), because the product may have changed since. It prints the reporter's
email only in `show`, so a list pasted somewhere carries none.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
import textwrap
from collections.abc import Sequence

from makhzan_schemas import overrides as rulings
from makhzan_schemas import reports as rules
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.models import Report

REASON_TEXT = {
    "offers_not_same": "These offers aren't the same product",
    "same_as_other": "The same as another product",
    "wrong_price_stock": "Wrong price or stock",
    "wrong_category": "Wrong category",
    "wrong_details": "Wrong details",
    "shop_contact": "A shop's contact details are wrong",
    "other": "Something else",
}


def _price(listing: dict) -> str:
    if listing.get("price") is None:
        return "no price"
    return f"{listing.get('currency') or 'EGP'} {listing['price']}"


def _listing_line(listing: dict) -> str:
    mark = "[x]" if listing.get("ticked") else "[ ]"
    shop = (listing.get("shop") or {}).get("name") or "?"
    return f"    {mark} {listing.get('title') or '(untitled)'} | {shop} | {_price(listing)} | {listing.get('stock')}"


def printable(text: str) -> str:
    """Text safe to print to a terminal: anything unprintable but a line break,
    escaped (`\x1b`), so nothing in a report can move the cursor, recolour the
    screen or write the clipboard (OSC 52). Intake strips control characters
    already (`makhzan_schemas.reports.strip_controls`); this covers rows from
    before that, and the snapshot's shop titles, which came from shops.
    """
    return "".join(
        ch if ch == "\n" or ch.isprintable() else ch.encode("unicode_escape").decode("ascii")
        for ch in text
    )


def format_report(report: Report, *, full: bool = False) -> str:
    """One report as text: what was said, and the offers as the page showed them."""
    snap = report.snapshot or {}
    product = snap.get("product") or {}
    lines = [
        f"{rules.reference(report.id)}  {report.created_at:%Y-%m-%d %H:%M} UTC  "
        f"[{report.status}{f' {report.reviewed_at:%Y-%m-%d}' if report.reviewed_at else ''}]",
        f"  {REASON_TEXT.get(report.reason, report.reason)}",
        f"  Product {report.product_id}: {product.get('title') or '(untitled)'}",
    ]
    if report.reported_product_id:
        lines.append(f"    (reported as {report.reported_product_id}, merged since)")
    if product.get("category_name"):
        lines.append(f"    filed under {product['category_name']} ({product.get('category')})")
    if report.field:
        said = f" -> {report.correct_value}" if report.correct_value else ""
        lines.append(f"  Field: {report.field}{said}")
    elif report.correct_value:
        lines.append(f"  Should be: {report.correct_value}")
    listings = product.get("listings") or []
    if listings:
        lines.append(f"  Offers then ({len(listings)}; [x] = ticked or picked):")
        lines.extend(_listing_line(x) for x in listings)
    other = snap.get("other_product")
    if other:
        lines.append(f"  Same as {other.get('id')}: {other.get('title') or '(untitled)'}")
        lines.extend(_listing_line(x) for x in other.get("listings") or [])
    if report.description:
        wrapped = textwrap.fill(
            report.description, width=88, initial_indent="  > ", subsequent_indent="  > "
        )
        lines.append(wrapped)
    if report.email:
        lines.append(f"  Reply to: {report.email}" if full else "  Reply wanted (email kept)")
    return printable("\n".join(lines))


async def _list(limit: int) -> int:
    async with SessionLocal() as session:
        rows = await rules.new_reports(session, limit=limit)
        total = await rules.count_new(session)
    if not rows:
        print("No new reports.")
        return 0
    print(
        f"{total} new report{'s' if total != 1 else ''}"
        + (f", the oldest {len(rows)} shown" if total > len(rows) else "")
    )
    for report in rows:
        print()
        print(format_report(report))
    print()
    print("Close one with: reports accept ID | reports reject ID  (ID is the number after R-)")
    return 0


async def _show(report_id: int) -> int:
    async with SessionLocal() as session:
        report = await session.get(Report, report_id)
    if report is None:
        print(f"No report {rules.reference(report_id)}.", file=sys.stderr)
        return 1
    print(format_report(report, full=True))
    return 0


def who(by: str | None) -> str:
    """Who is acting: as given, else the login running the command."""
    if by and by.strip():
        return by.strip()
    try:
        return getpass.getuser()
    except (KeyError, OSError):
        return "cli"


async def _review(ids: Sequence[int], status: str, by: str | None = None) -> int:
    missing = 0
    async with SessionLocal() as session:
        for report_id in ids:
            pairs = None
            if status == "accepted":
                # The rulings first: a report no ruling could act on is
                # refused, not shown accepted with nothing behind it.
                found = await session.get(Report, report_id)
                if found is not None:
                    try:
                        pairs = await rulings.report_pairs(session, found)
                    except rulings.ReportRefused as refused:
                        print(
                            f"{rules.reference(report_id)} not accepted: {refused}. "
                            "Reject it, or rule by hand with `overrides add`.",
                            file=sys.stderr,
                        )
                        missing += 1
                        continue
            report = await rules.review(session, report_id, status)
            if report is None:
                print(f"No report {rules.reference(report_id)}.", file=sys.stderr)
                missing += 1
                continue
            print(f"{rules.reference(report_id)} {status}.")
            if status == "accepted":
                added_all = await rulings.accept_report(
                    session, report, created_by=who(by), pairs=pairs
                )
                for added in added_all:
                    print("  " + ruling_line(added))
            else:
                withdrawn = await rulings.withdraw_report(session, report_id)
                if withdrawn:
                    print(f"  withdrew {withdrawn} grouping override(s) it had made")
            await session.commit()
    return 1 if missing else 0


def ruling_line(added: rulings.Added) -> str:
    """One recorded (or refused) ruling, for the command's output."""
    row = added.row
    said = {
        "created": "override",
        "exists": "already there: override",
        "conflict": "NOT recorded, the pair has the other ruling: override",
    }[added.outcome]
    return (
        f"{said} #{row.id} {row.kind}{' forced' if row.forced else ''} "
        f"{row.listing_a} {row.listing_b} (applies at the next regroup)"
    )


async def _purge() -> int:
    async with SessionLocal() as session:
        counts = await rules.purge_personal_data(session)
    print(f"Erased {counts['emails']} emails and {counts['ip_hashes']} address hashes.")
    return 0


def _report_id(value: str) -> int:
    value = value.strip().upper().removeprefix("R-")
    if not value.isdigit():
        raise argparse.ArgumentTypeError(f"not a report id: {value!r} (e.g. 24817 or R-24817)")
    return int(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="reports", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command")
    listing = sub.add_parser("list", help="new reports, oldest first")
    listing.add_argument("--limit", type=int, default=50)
    show = sub.add_parser("show", help="one report in full, its email included")
    show.add_argument("id", type=_report_id)
    for verb in ("accept", "reject"):
        p = sub.add_parser(verb, help=f"{verb} one or more reports")
        p.add_argument("ids", type=_report_id, nargs="+")
        p.add_argument("--by", help="who is reviewing, recorded on any override (default: login)")
    sub.add_parser("purge", help="erase expired emails and address hashes now")
    return parser


async def run(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command in (None, "list"):
        return await _list(getattr(args, "limit", 50))
    if args.command == "show":
        return await _show(args.id)
    if args.command == "purge":
        return await _purge()
    status = "accepted" if args.command == "accept" else "rejected"
    return await _review(args.ids, status, args.by)


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
