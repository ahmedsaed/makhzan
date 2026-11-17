"""The product rebuild's job id: one `rebuild_and_reindex` per window, run at its end.

Shared by the ingestion worker (`worker.main.request_rebuild`, after every
source job) and the AI broker (after a worker's window, P16), which runs from
the API image and cannot import the worker. Sources and sessions finishing in
one window share one rebuild; one finishing later gets the next window's.
Nothing is lost to the dedup: a window's rebuild runs after everything that
asked for it.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

#: Sources finishing within one window of this many seconds share one rebuild,
#: run at the end of that window. Short next to a crawl, long next to a rebuild.
REBUILD_WINDOW = int(os.getenv("REBUILD_WINDOW_SECONDS", "600"))

#: The arq function the worker registers.
REBUILD_FUNCTION = "rebuild_and_reindex"


def rebuild_job_id(now: datetime, window_seconds: int = REBUILD_WINDOW) -> tuple[str, datetime]:
    """The rebuild job for `now`'s window, and when it runs: the window's end."""
    window = int(now.timestamp()) // window_seconds
    runs_at = datetime.fromtimestamp((window + 1) * window_seconds, timezone.utc)
    return f"rebuild:{window}", runs_at
