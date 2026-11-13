""" "Report a problem": the vocabulary, the retention rules, and the review.

Shared by the API (which takes reports in, `POST /reports`) and the worker
(which erases what the privacy page says is erased, and which the
`./makhzan reports` command runs to review them). The page that states these
rules to visitors is apps/web/app/(site)/privacy; change one, change both.

Not here, on purpose: turning accepted reports into labelled pairs for
matching (docs/ai/plan.md, phase G). The rows keep what that step needs (the
reason, the offers ticked, the other product, and the snapshot of every offer
the visitor saw), and nothing more.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from makhzan_schemas.models import Report

#: What the visitor says is wrong. The table's check constraint holds the same list.
REASONS = (
    "offers_not_same",
    "same_as_other",
    "wrong_price_stock",
    "wrong_category",
    "wrong_details",
    "shop_contact",
    "other",
)

#: Which detail is wrong, per reason. A reason not named here takes no field.
FIELDS_BY_REASON: dict[str, tuple[str, ...]] = {
    "wrong_price_stock": ("price", "stock"),
    "wrong_category": ("category",),
    "wrong_details": ("title", "specs", "photo", "description"),
    "shop_contact": ("phone", "whatsapp", "hours", "address"),
}
FIELDS = tuple(f for fields in FIELDS_BY_REASON.values() for f in fields)

#: What a stock report may say the shop's site shows.
STOCK_VALUES = ("in_stock", "out_of_stock", "gone")

STATUSES = ("new", "accepted", "rejected")

#: The free text's limit. Longer is dropped as spam, not cut.
MAX_DESCRIPTION = 1000
#: More links than this in the free text is dropped as spam.
MAX_LINKS = 2
#: A report sent sooner than this after the form opened is dropped as a bot.
MIN_FILL_SECONDS = 3.0
#: Per address (its salted hash): at most this many stored reports an hour, and a day.
PER_HOUR = 5
PER_DAY = 20

#: An email is erased this long after its report is closed (reviewed).
EMAIL_KEPT_AFTER_CLOSED = timedelta(days=90)
#: An address's hash is erased this long after the report was sent.
IP_HASH_KEPT = timedelta(hours=24)


def reference(report_id: int) -> str:
    """What the visitor is shown, and quotes if they write: "R-24817"."""
    return f"R-{report_id}"


async def purge_personal_data(
    session: AsyncSession, *, now: datetime | None = None
) -> dict[str, int]:
    """Erase what the privacy page says is not kept, and commit.

    The email 90 days after the report was closed; the address's hash 24 hours
    after it was sent. The report itself stays. Idempotent: run hourly by the
    worker's cron (`worker.main.purge_reports`), so nothing outlives its limit
    by more than an hour.
    """
    now = now or datetime.now(UTC)
    emails = await session.execute(
        update(Report)
        .where(
            Report.email.is_not(None),
            Report.reviewed_at.is_not(None),
            Report.reviewed_at <= now - EMAIL_KEPT_AFTER_CLOSED,
        )
        .values(email=None)
        .execution_options(synchronize_session=False)
    )
    hashes = await session.execute(
        update(Report)
        .where(Report.ip_hash.is_not(None), Report.created_at <= now - IP_HASH_KEPT)
        .values(ip_hash=None)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    return {"emails": emails.rowcount or 0, "ip_hashes": hashes.rowcount or 0}


async def new_reports(session: AsyncSession, *, limit: int = 50) -> list[Report]:
    """Reports nobody has reviewed yet, oldest first."""
    rows = await session.scalars(
        select(Report).where(Report.status == "new").order_by(Report.id).limit(limit)
    )
    return list(rows)


async def count_new(session: AsyncSession) -> int:
    return await session.scalar(
        select(func.count()).select_from(Report).where(Report.status == "new")
    )


async def review(
    session: AsyncSession, report_id: int, status: str, *, now: datetime | None = None
) -> Report | None:
    """Close a report as `accepted` or `rejected`, and commit. None if there is no such report.

    Reviewing again changes the verdict and its time: a mistake can be put
    right. The email's 90 days count from the latest review.
    """
    if status not in ("accepted", "rejected"):
        raise ValueError(f"a report is accepted or rejected, not {status!r}")
    report = await session.get(Report, report_id)
    if report is None:
        return None
    report.status = status
    report.reviewed_at = now or datetime.now(UTC)
    await session.commit()
    return report
