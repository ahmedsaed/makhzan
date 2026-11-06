"""Run one source by hand:  python -m worker.ingest SOURCE_ID [LIMIT]

A LIMIT makes the run ephemeral — cursors untouched, nothing archived — which is
what to use for testing so a real sweep's resume point is left alone. Disabled
sources run too; `enabled` only governs the daily refresh.
"""

from __future__ import annotations

import asyncio
import sys

from worker.pipeline import run_source
from worker.sources.registry import get, load_adapters


async def main(source_id: str, limit: int | None) -> None:
    errors = await load_adapters()
    if source_id in errors:
        raise SystemExit(f"{source_id} does not build: {errors[source_id]}")
    try:
        adapter = get(source_id)
    except KeyError:
        raise SystemExit(f"no source {source_id!r} in the sources table — run `make sources`")
    run = await run_source(source_id, adapter, limit=limit)
    print(
        run.status,
        "seen",
        run.items_seen,
        "created",
        run.items_created,
        "updated",
        run.items_updated,
    )


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        raise SystemExit(__doc__)
    asyncio.run(main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) == 3 else None))
