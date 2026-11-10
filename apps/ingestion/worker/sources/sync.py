"""Seed the `sources` table from sources.toml.

    python -m worker.sources.sync [PATH]      # default: $MAKHZAN_SOURCES, else config/

Every source in the file is upserted by `id`; a row the file does not name is
left alone and reported, since the table is the runtime source of truth and may
hold sources added some other way. The file wins for every source it does name,
`enabled` included.

Each source's `supplier` table also owns the shop's listed contact details (phone,
WhatsApp, email, address, map link, hours, branches, and where and when a person
read them: see `SupplierInfo`). They are written onto the shop's Supplier row
here, on every sync, all of them, so the file is their only writer and a value
removed from it is cleared. A shop not crawled yet has no row; the pipeline
creates it, with the same details, on its first run.

Nothing is written unless the whole file is valid: each entry is built into its
adapter first — crosswalk loaded, constructor called — so a typo'd key or a
missing crosswalk fails here, at deploy, instead of on the next daily run.
"""

from __future__ import annotations

import asyncio
import sys
import tomllib
from datetime import date
from pathlib import Path

from makhzan_schemas.config import sources_file
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.models import Source, Supplier
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from worker.sources.base import SupplierInfo
from worker.sources.registry import build_adapter

#: Keys that are columns. Everything else in an entry is adapter config.
_COLUMNS = {"id", "adapter", "base_url", "enabled", "supplier"}


def read_sources(path: Path) -> list[Source]:
    """Parse and validate a sources file into (unsaved) Source rows."""
    with path.open("rb") as f:
        entries = tomllib.load(f).get("source", [])

    rows: list[Source] = []
    seen: set[str] = set()
    for i, entry in enumerate(entries, 1):
        missing = {"id", "adapter", "supplier"} - set(entry)
        if missing:
            raise ValueError(f"{path}: source #{i} is missing {sorted(missing)}")
        if entry["id"] in seen:
            raise ValueError(f"{path}: duplicate source id {entry['id']!r}")
        seen.add(entry["id"])

        row = Source(
            source_id=entry["id"],
            adapter=entry["adapter"],
            base_url=entry.get("base_url"),
            enabled=entry.get("enabled", True),
            supplier=_stored_form(entry["supplier"]),
            config={k: v for k, v in entry.items() if k not in _COLUMNS},
        )
        try:
            build_adapter(row)
        except Exception as exc:
            raise ValueError(f"{path}: source {entry['id']!r} does not build: {exc}") from exc
        rows.append(row)
    _check_shared_shops(path, rows)
    return rows


def _stored_form(value: object) -> object:
    """A supplier table as the JSONB column can hold it: TOML dates become ISO text."""
    if isinstance(value, dict):
        return {k: _stored_form(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_stored_form(v) for v in value]
    if isinstance(value, date):
        return value.isoformat()
    return value


def _check_shared_shops(path: Path, rows: list[Source]) -> None:
    """Two sources for one shop must not give it two different sets of contact details.

    Both would be written to the one Supplier row, and which won would depend on
    the order of the file.
    """
    seen: dict[str, tuple[str, dict]] = {}
    for row in rows:
        info = SupplierInfo(**row.supplier)
        details = {k: v for k, v in info.contact_columns().items() if v is not None}
        earlier = seen.get(info.slug)
        if earlier is None or not earlier[1]:
            seen[info.slug] = (row.source_id, details)
        elif details and details != earlier[1]:
            raise ValueError(
                f"{path}: sources {earlier[0]!r} and {row.source_id!r} give shop "
                f"{info.slug!r} different contact details; list them on one of the two"
            )


async def _write_contact(session: AsyncSession, rows: list[Source]) -> list[str]:
    """Write each shop's listed contact details onto its Supplier row. Returns the slugs changed."""
    columns: dict[str, dict] = {}
    for row in rows:
        info = SupplierInfo(**row.supplier)
        details = info.contact_columns()
        # A shop named by two sources: the one that lists details (checked above
        # to agree with any other that does).
        if info.slug not in columns or any(v is not None for v in details.values()):
            columns[info.slug] = details
    suppliers = (
        await session.execute(select(Supplier).where(Supplier.slug.in_(list(columns))))
    ).scalars()
    changed: list[str] = []
    for supplier in suppliers:
        updated = False
        for name, value in columns[supplier.slug].items():
            if getattr(supplier, name) != value:
                setattr(supplier, name, value)
                updated = True
        if updated:
            changed.append(supplier.slug)
    return sorted(changed)


async def sync_sources(session: AsyncSession, rows: list[Source]) -> dict[str, list[str]]:
    """Upsert `rows` by source_id. Returns what changed, for the caller to print."""
    existing = {s.source_id: s for s in (await session.execute(select(Source))).scalars()}
    report: dict[str, list[str]] = {
        "created": [],
        "updated": [],
        "unchanged": [],
        "not_in_file": [],
        "shop_details": [],
    }
    for row in rows:
        current = existing.pop(row.source_id, None)
        if current is None:
            session.add(row)
            report["created"].append(row.source_id)
            continue
        changed = False
        for field in ("adapter", "base_url", "enabled", "supplier", "config"):
            if getattr(current, field) != getattr(row, field):
                setattr(current, field, getattr(row, field))
                changed = True
        report["updated" if changed else "unchanged"].append(row.source_id)
    report["not_in_file"] = sorted(existing)
    report["shop_details"] = await _write_contact(session, rows)
    await session.commit()
    return report


async def main(path: Path) -> None:
    rows = read_sources(path)
    async with SessionLocal() as session:
        report = await sync_sources(session, rows)
    print(f"sources from {path}:")
    for outcome, ids in report.items():
        if ids:
            print(f"  {outcome:12} {', '.join(ids)}")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1]) if len(sys.argv) > 1 else sources_file()))
