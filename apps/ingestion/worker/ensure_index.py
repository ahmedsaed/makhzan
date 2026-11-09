"""Apply the search index's settings: `python -m worker.ensure_index`.

Run by the `migrate` service on every deploy, before the API starts, so the
index always knows the attributes the new code filters and sorts on. Without
this, a release that makes an attribute filterable (the stale filter's
`last_verified_at`) breaks search from the deploy until the next reindex.

Settings only: documents are untouched, so this is fast and safe to repeat.
Meilisearch may still be starting when `migrate` runs, so it waits for it.
"""

from __future__ import annotations

import sys
import time

import meilisearch

from worker.indexer import ensure_index, get_client

ATTEMPTS = 30
WAIT_SECONDS = 2.0


def main() -> int:
    for attempt in range(1, ATTEMPTS + 1):
        try:
            ensure_index(get_client())
        except (meilisearch.errors.MeilisearchCommunicationError, OSError) as exc:
            if attempt == ATTEMPTS:
                print(f"search index settings not applied: {exc}", file=sys.stderr)
                return 1
            time.sleep(WAIT_SECONDS)
            continue
        print("search index settings applied")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
