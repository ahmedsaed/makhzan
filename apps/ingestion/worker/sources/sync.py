"""Seed the `sources` table from sources.toml.

    python -m worker.sources.sync [PATH]      # default: $MAKHZAN_SOURCES, else config/

Every source in the file is upserted by `id`; a row the file does not name is
left alone and reported, since the table is the runtime source of truth and may
hold sources added some other way. The file wins for every source it does name,
`enabled` included.

Nothing is written unless the whole file is valid: each entry is built into its
adapter first — crosswalk loaded, constructor called — so a typo'd key or a
missing crosswalk fails here, at deploy, instead of on the next daily run.
"""

from __future__ import annotations

import asyncio
import sys
import tomllib
from pathlib import Path

from makhzan_schemas.config import sources_file
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.models import Source
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
            supplier=dict(entry["supplier"]),
            config={k: v for k, v in entry.items() if k not in _COLUMNS},
        )
        try:
            build_adapter(row)
        except Exception as exc:
            raise ValueError(f"{path}: source {entry['id']!r} does not build: {exc}") from exc
        rows.append(row)
    return rows


async def sync_sources(session: AsyncSession, rows: list[Source]) -> dict[str, list[str]]:
    """Upsert `rows` by source_id. Returns what changed, for the caller to print."""
    existing = {s.source_id: s for s in (await session.execute(select(Source))).scalars()}
    report: dict[str, list[str]] = {
        "created": [],
        "updated": [],
        "unchanged": [],
        "not_in_file": [],
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
