"""grouping overrides

The `grouping_overrides` table: a person's ruling that two listings are never,
or must be, one product. The regroup (`grouping.rebuild_products`) reads it as
a veto (never_merge) or as evidence that admits the pair (must_merge, which
`forced` lets past the value, form and price vetoes too); `./makhzan reports
accept` writes it from "Report a problem", `./makhzan overrides add` by hand.

Keyed by the unordered listing pair (stored listing_a < listing_b, one ruling
a pair), because listing ids are permanent. A new table, so expand-only: the
release still serving during the deploy never reads it, and a regroup with an
empty table groups exactly as before.

Revision ID: ade77037df65
Revises: 79044872e5b3
Create Date: 2026-11-16 20:24:58.259781

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ade77037df65"
down_revision: str | Sequence[str] | None = "79044872e5b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "grouping_overrides",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("listing_a", sa.UUID(), nullable=False),
        sa.Column("listing_b", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("forced", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("listing_a < listing_b", name="ck_grouping_override_ordered"),
        sa.CheckConstraint(
            "kind IN ('never_merge', 'must_merge')", name="ck_grouping_override_kind"
        ),
        sa.CheckConstraint(
            "NOT forced OR kind = 'must_merge'", name="ck_grouping_override_forced_must"
        ),
        sa.CheckConstraint("source IN ('report', 'manual')", name="ck_grouping_override_source"),
        sa.CheckConstraint(
            "(source = 'report') = (report_id IS NOT NULL)", name="ck_grouping_override_report"
        ),
        sa.CheckConstraint(
            "source <> 'manual' OR length(trim(note)) > 0",
            name="ck_grouping_override_manual_note",
        ),
        sa.ForeignKeyConstraint(["listing_a"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["listing_b"], ["listings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("listing_a", "listing_b", name="uq_grouping_override_pair"),
    )
    op.create_index(op.f("ix_grouping_overrides_listing_b"), "grouping_overrides", ["listing_b"])
    op.create_index(op.f("ix_grouping_overrides_report_id"), "grouping_overrides", ["report_id"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_grouping_overrides_report_id"), table_name="grouping_overrides")
    op.drop_index(op.f("ix_grouping_overrides_listing_b"), table_name="grouping_overrides")
    op.drop_table("grouping_overrides")
