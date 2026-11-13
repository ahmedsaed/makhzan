"""reports

The `reports` table behind "Report a problem" on product pages (POST /reports),
the API's first write from a visitor. One row per report: the reason, the
offers ticked, the other product, what it should say, the free text, an
optional email, and a snapshot of the offers as the page showed them.

A new table, so expand-only: the release still serving during the deploy never
reads it. `product_id` and `other_product_id` are deliberately not foreign
keys (a merged product's row can be retired, and a report must outlive it).
Retention (`makhzan_schemas.reports`): the email is erased 90 days after the
report is closed and `ip_hash` 24 hours after it was sent, by the worker's
hourly cron.

Revision ID: 79044872e5b3
Revises: 2db8f3d44c3c
Create Date: 2026-11-13 19:23:23.014497

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "79044872e5b3"
down_revision: str | Sequence[str] | None = "2db8f3d44c3c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column("reported_product_id", sa.UUID(), nullable=True),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("offer_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("other_product_id", sa.UUID(), nullable=True),
        sa.Column("field", sa.String(length=32), nullable=True),
        sa.Column("correct_value", sa.String(length=200), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="new", nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(status = 'new') = (reviewed_at IS NULL)", name="ck_report_reviewed_when_closed"
        ),
        sa.CheckConstraint(
            "reason IN ('offers_not_same', 'same_as_other', 'wrong_price_stock', "
            "'wrong_category', 'wrong_details', 'shop_contact', 'other')",
            name="ck_report_reason",
        ),
        sa.CheckConstraint("status IN ('new', 'accepted', 'rejected')", name="ck_report_status"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_ip_hash_created", "reports", ["ip_hash", "created_at"])
    op.create_index("ix_report_status_created", "reports", ["status", "created_at"])
    op.create_index(op.f("ix_reports_product_id"), "reports", ["product_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_reports_product_id"), table_name="reports")
    op.drop_index("ix_report_status_created", table_name="reports")
    op.drop_index("ix_report_ip_hash_created", table_name="reports")
    op.drop_table("reports")
