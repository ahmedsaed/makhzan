"""Operational status for the crawlers: `make status`.

The report lives in the ingestion package, `worker/status.py`, so the admin
dashboard (apps/ingestion/admin) can render the same data the terminal prints.
This script only runs it:

    python scripts/status.py [--source SOURCE] [--runs N]
    python -m worker.status [--source SOURCE] [--runs N]     # the same
"""

from __future__ import annotations

import asyncio

from worker.status import *  # noqa: F403 — the report's sections, for callers of this path
from worker.status import main

if __name__ == "__main__":
    asyncio.run(main())
