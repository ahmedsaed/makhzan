"""Pausing the crawl, all of it or one shop, without touching configuration.

    python -m worker.pause crawl                     # show the crawl-wide switches
    python -m worker.pause crawl off [--note "why"] [--by NAME]
    python -m worker.pause crawl on [--by NAME]
    python -m worker.pause shop                      # every source, paused ones marked
    python -m worker.pause shop pause SOURCE [--note "why"] [--by NAME]
    python -m worker.pause shop resume SOURCE [--by NAME]

`./makhzan crawl` and `./makhzan shop` run this in the production worker; the
admin dashboard calls the same functions. Both pauses live in the database,
so neither needs a container recreated and both survive deploys:

- **The crawl-wide pause** is `worker_state["crawl_pause"]`
  (`makhzan_schemas.crawl`). It sits over `CRAWL_ENABLED`, the environment
  switch the worker reads when its container is created: the crawl runs only
  when that is on *and* nothing is paused.
- **A shop's pause** is `sources.paused_at` (with `paused_by`, `pause_note`).
  It sits over `enabled`, which is sources.toml's and rewritten by every sync
  (`worker.sources.sync` never writes the pause columns).

Paused, nothing new starts: `refresh_all` queues no daily job for it and a
`crawl_source` job already queued skips it. A full run already going reads
the pause before every page (`paused_reason`) and stops there, keeping its
cursors, as it does when its time is up; it records `stats.stopped`. A
`limit=` run (the dashboard's "Run now") and the probe still work on a paused
shop: they are how a blocked shop is looked at before it is resumed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence

from makhzan_schemas import crawl
from makhzan_schemas.db import SessionLocal
from makhzan_schemas.models import Source
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from worker.reports import who


async def paused_reason(session: AsyncSession, source_id: str) -> str | None:
    """Why a full run of `source_id` must not go on, or None: the crawl or the shop is paused."""
    pause = await crawl.crawl_pause(session)
    if pause is not None:
        return f"crawl paused by {pause.get('by') or '?'}"
    row = (
        await session.execute(
            select(Source.paused_at, Source.paused_by).where(Source.source_id == source_id)
        )
    ).one_or_none()
    if row is not None and row.paused_at is not None:
        return f"shop paused by {row.paused_by or '?'}"
    return None


async def paused_sources(session: AsyncSession) -> set[str]:
    """Every source id a person has paused."""
    return set(await session.scalars(select(Source.source_id).where(Source.paused_at.is_not(None))))


async def pause_source(
    session: AsyncSession, source_id: str, *, by: str, note: str | None = None
) -> Source | None:
    """Pause one source (flushed, not committed); None if there is no such source.

    Pausing a paused source changes nothing, so the first pause's time and
    reason are kept.
    """
    row = await session.scalar(select(Source).where(Source.source_id == source_id))
    if row is None:
        return None
    if row.paused_at is None:
        row.paused_at = await session.scalar(select(func.now()))
        row.paused_by = by.strip()[:100] or "cli"
        row.pause_note = (note or "").strip() or None
        await session.flush()
    return row


async def resume_source(session: AsyncSession, source_id: str) -> Source | None:
    """Clear one source's pause (flushed, not committed); None if there is no such source.

    Resuming a paused source stamps `resumed_at`: the archive confirmation's
    hold window runs from there, so a long pause does not make the first run
    after it give up on its candidates as overdue.
    """
    row = await session.scalar(select(Source).where(Source.source_id == source_id))
    if row is None:
        return None
    if row.paused_at is not None:
        row.resumed_at = await session.scalar(select(func.now()))
    row.paused_at = row.paused_by = row.pause_note = None
    await session.flush()
    return row


async def _crawl(value: str | None, note: str | None, by: str) -> int:
    async with SessionLocal() as session:
        if value is not None:
            await crawl.set_crawl_pause(session, value == "off", by=by, note=note)
            await session.commit()
        env = await crawl.worker_crawl_enabled(session)
        pause = await crawl.crawl_pause(session)
    print(f"CRAWL_ENABLED (the worker's environment): {'on' if env else 'off'}")
    if pause is None:
        print("pause (database): none")
    else:
        why = f": {pause['note']}" if pause.get("note") else ""
        print(f"pause (database): paused by {pause.get('by')} at {pause.get('at')}{why}")
    print(f"=> the daily crawl is {'on' if env and pause is None else 'OFF'}")
    return 0


async def _shop_list() -> int:
    async with SessionLocal() as session:
        rows = list(await session.scalars(select(Source).order_by(Source.source_id)))
    for row in rows:
        state = "enabled" if row.enabled else "disabled in sources.toml"
        if row.paused_at is not None:
            note = f": {row.pause_note}" if row.pause_note else ""
            state += f", PAUSED {row.paused_at:%Y-%m-%d %H:%M} UTC by {row.paused_by}{note}"
        print(f"{row.source_id:<24} {state}")
    if not rows:
        print("No sources.")
    return 0


async def _shop(action: str, source_id: str, note: str | None, by: str) -> int:
    async with SessionLocal() as session:
        if action == "pause":
            row = await pause_source(session, source_id, by=by, note=note)
        else:
            row = await resume_source(session, source_id)
        await session.commit()
    if row is None:
        print(f"No source {source_id!r}.", file=sys.stderr)
        return 1
    if action == "pause":
        print(f"{source_id} paused by {row.paused_by}: the daily run skips it until resumed.")
    else:
        print(f"{source_id} resumed: its next daily run sweeps it again.")
    if not row.enabled:
        print("  (it is also disabled in sources.toml, which keeps it off either way)")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pause", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("crawl", help="the crawl-wide pause; no argument shows it")
    c.add_argument("value", nargs="?", choices=("on", "off"))
    c.add_argument("--note", help="why (kept with the pause)")
    c.add_argument("--by", help="who (default: login)")
    s = sub.add_parser("shop", help="one source's pause; no argument lists every source")
    s.add_argument("action", nargs="?", choices=("pause", "resume"))
    s.add_argument("source", nargs="?")
    s.add_argument("--note", help="why (kept with the pause)")
    s.add_argument("--by", help="who (default: login)")
    return parser


async def run(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "crawl":
        return await _crawl(args.value, args.note, who(args.by))
    if args.action is None:
        return await _shop_list()
    if not args.source:
        parser.error(f"shop {args.action} needs a source id")
    return await _shop(args.action, args.source, args.note, who(args.by))


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
