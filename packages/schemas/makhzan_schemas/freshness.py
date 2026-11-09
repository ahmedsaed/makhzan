"""When a price stops being worth showing by default.

**Stale** means last checked more than `STALE_AFTER_DAYS` whole days ago. It is
the "warn" tier of the site's freshness rules (docs/DESIGN.md F2, "Price may be
out of date") and the line the stale filter draws (C2b), so a price that the
page warns about and a product the filter hides are the same thing.

The web app holds the same number as `STALE_AFTER_DAYS` in
`apps/web/lib/freshness.ts`, and a test there reads this file to keep the two
equal. Change both, or neither.

A *product* is fresh when any of its offers is: the search document's
`last_verified_at` is the newest of its listings' (`grouping.rebuild_products`),
the same "any" that `in_stock` aggregates with.
"""

from __future__ import annotations

from datetime import UTC, datetime

STALE_AFTER_DAYS = 45

_DAY = 86_400


def fresh_since(now: datetime | None = None) -> int:
    """The epoch second a check must be *after* to count as fresh.

    The web counts whole days, rounding down, and warns from day 46: a check
    45 days and 23 hours old still reads "45 days" and is not stale. So the
    cutoff is 46 full days back, and fresh is strictly newer than it.
    """
    now = now or datetime.now(UTC)
    return int(now.timestamp()) - (STALE_AFTER_DAYS + 1) * _DAY
