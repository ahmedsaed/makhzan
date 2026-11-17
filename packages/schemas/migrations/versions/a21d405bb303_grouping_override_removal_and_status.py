"""grouping override removal and status

Two owner decisions on `grouping_overrides`:

- Removing a ruling keeps its row: `removed_at` and `removed_by`. The regroup
  ignores a removed ruling, cites it on the change that undoes its effect, and
  the pair may be ruled on again as a new row, so the one-ruling-a-pair rule
  becomes a unique index over standing rows only.
- A forced ruling an existing product blocks stays inactive, but is shown:
  after each regroup `status` (in_effect / blocked / inactive / removed),
  `blocked_by`, `blocked_reason` and `checked_at` say whether it holds and,
  when not, which listing kept the pair apart and why.

Expand-only but for the unique constraint, which becomes a partial index; no
row can break it, since until now no row was ever removed. The downgrade
deletes removed rows before restoring the full constraint.

Revision ID: a21d405bb303
Revises: ade77037df65
Create Date: 2026-11-16 21:51:45.750399

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a21d405bb303"
down_revision: str | Sequence[str] | None = "ade77037df65"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "grouping_overrides", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "grouping_overrides", sa.Column("removed_by", sa.String(length=100), nullable=True)
    )
    op.add_column("grouping_overrides", sa.Column("status", sa.String(length=16), nullable=True))
    op.add_column("grouping_overrides", sa.Column("blocked_by", sa.UUID(), nullable=True))
    op.add_column("grouping_overrides", sa.Column("blocked_reason", sa.Text(), nullable=True))
    op.add_column(
        "grouping_overrides", sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        "ck_grouping_override_removed_by",
        "grouping_overrides",
        "(removed_at IS NULL) = (removed_by IS NULL)",
    )
    op.create_check_constraint(
        "ck_grouping_override_status",
        "grouping_overrides",
        "status IS NULL OR status IN ('in_effect', 'blocked', 'inactive', 'removed')",
    )
    op.drop_constraint("uq_grouping_override_pair", "grouping_overrides", type_="unique")
    op.create_index(
        "uq_grouping_override_standing_pair",
        "grouping_overrides",
        ["listing_a", "listing_b"],
        unique=True,
        postgresql_where=sa.text("removed_at IS NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM grouping_overrides WHERE removed_at IS NOT NULL")
    op.drop_index(
        "uq_grouping_override_standing_pair",
        table_name="grouping_overrides",
        postgresql_where=sa.text("removed_at IS NULL"),
    )
    op.create_unique_constraint(
        "uq_grouping_override_pair", "grouping_overrides", ["listing_a", "listing_b"]
    )
    op.drop_constraint("ck_grouping_override_status", "grouping_overrides", type_="check")
    op.drop_constraint("ck_grouping_override_removed_by", "grouping_overrides", type_="check")
    op.drop_column("grouping_overrides", "checked_at")
    op.drop_column("grouping_overrides", "blocked_reason")
    op.drop_column("grouping_overrides", "blocked_by")
    op.drop_column("grouping_overrides", "status")
    op.drop_column("grouping_overrides", "removed_by")
    op.drop_column("grouping_overrides", "removed_at")
