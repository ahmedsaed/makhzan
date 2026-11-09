"""Drop product redirects nobody has followed in a year.

    python -m worker.retire_redirects            # drop them
    python -m worker.retire_redirects --dry-run  # count them, change nothing

A redirect is kept for as long as someone uses it, so the list does not grow
for ever (docs/decisions/0005-url-retirement.md). Two kinds are data, and both
retire here:

- a merged-away product (`Product.merged_into`): its row is deleted. It has no
  offers, so nothing is lost but the redirect; its `product_events` stay.
- an id deleted before ids became permanent (`ProductRedirect`).

"Unused" is measured from when the redirect was last followed (the API records
it, at most once a day), or from when it was created if it never has been. The
first rebuild job of each day runs this after the regroup
(`worker.main.retire_redirects_daily`); it is a no-op until the oldest redirect
is a year old (November 2027).
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta

from makhzan_schemas.db import SessionLocal
from makhzan_schemas.grouping import lock_products
from makhzan_schemas.models import Product, ProductRedirect
from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

#: How long a redirect may go unused before it is dropped.
UNUSED_FOR = timedelta(days=365)


async def retire_unused_redirects(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    unused_for: timedelta = UNUSED_FOR,
    dry_run: bool = False,
) -> dict[str, int]:
    """Delete redirects last used (or, never used, created) before `now - unused_for`."""
    # A regroup in another process could be un-merging a row this would delete.
    await lock_products(session)
    cutoff = (now or datetime.now(UTC)) - unused_for
    pointing = aliased(Product)
    merged = (
        Product.merged_into.is_not(None),
        func.coalesce(Product.redirect_used_at, Product.merged_at, Product.updated_at) < cutoff,
        # Never true, since every merge repoints whatever led to the product it
        # absorbs; checked anyway, because a deleted target would leave the
        # redirects that lead to it nowhere to go.
        ~exists().where(pointing.merged_into == Product.id),
        ~exists().where(ProductRedirect.new_id == Product.id),
    )
    legacy = (func.coalesce(ProductRedirect.last_used_at, ProductRedirect.created_at) < cutoff,)
    counts = {
        "merged_products": await session.scalar(
            select(func.count()).select_from(Product).where(*merged)
        ),
        "product_redirects": await session.scalar(
            select(func.count()).select_from(ProductRedirect).where(*legacy)
        ),
    }
    if not dry_run:
        await session.execute(delete(Product).where(*merged))
        await session.execute(delete(ProductRedirect).where(*legacy))
        await session.commit()
    else:
        await session.rollback()  # releases the lock
    return counts


async def main(dry_run: bool) -> None:
    async with SessionLocal() as session:
        counts = await retire_unused_redirects(session, dry_run=dry_run)
    verb = "would drop" if dry_run else "dropped"
    print(
        f"{verb} {counts['merged_products']} merged product ids and "
        f"{counts['product_redirects']} older product redirects unused for "
        f"{UNUSED_FOR.days} days",
        flush=True,
    )


if __name__ == "__main__":
    asyncio.run(main(dry_run="--dry-run" in sys.argv[1:]))
