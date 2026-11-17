"""ai review fixes

What the broker's reviews asked of the schema, expand-only:

- `ai_jobs.in_hand_at`: the job a worker's heartbeat said it was scoring.
  When a lease expires only that job is charged an attempt; its co-leased
  jobs go back to the queue free, so one poison job no longer kills others.
- `ai_flags.subject`, part of `uq_ai_flag_open`: a version drift is one
  open flag per worker and model ("<worker>/<model>"), not one global row.
  The index is rebuilt with the column; existing open flags keep a NULL
  subject and stay unique.
- `ai_sessions.last_lease_request` / `last_lease_id`: a retried /lease with
  the same `lease_request_id` gets the same jobs back.

The downgrade first dismisses all but the oldest open flag per (kind,
listing_a, listing_b), which the old unique index cannot hold (two workers'
drift flags differ only by subject).

Revision ID: a9a0252aacef
Revises: 895dafa67c0d
Create Date: 2026-11-17 16:05:07.129679

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9a0252aacef"
down_revision: str | Sequence[str] | None = "895dafa67c0d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("ai_flags", sa.Column("subject", sa.String(length=100), nullable=True))
    op.drop_index(
        op.f("uq_ai_flag_open"),
        table_name="ai_flags",
        postgresql_where="((status)::text = 'open'::text)",
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "uq_ai_flag_open",
        "ai_flags",
        ["kind", "listing_a", "listing_b", "subject"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
        postgresql_nulls_not_distinct=True,
    )
    op.add_column("ai_jobs", sa.Column("in_hand_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "ai_sessions", sa.Column("last_lease_request", sa.String(length=64), nullable=True)
    )
    op.add_column("ai_sessions", sa.Column("last_lease_id", sa.UUID(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("ai_sessions", "last_lease_id")
    op.drop_column("ai_sessions", "last_lease_request")
    op.drop_column("ai_jobs", "in_hand_at")
    # The old index cannot hold what the new one allows.
    op.execute(
        """
        UPDATE ai_flags
           SET status = 'dismissed', resolved_at = now(), resolved_by = 'migration',
               note = 'closed by downgrade a9a0252aacef: one open flag per pair before it'
         WHERE status = 'open'
           AND id NOT IN (
               SELECT min(id) FROM ai_flags WHERE status = 'open'
                GROUP BY kind, listing_a, listing_b
           )
        """
    )
    op.drop_index(
        "uq_ai_flag_open",
        table_name="ai_flags",
        postgresql_where=sa.text("status = 'open'"),
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        op.f("uq_ai_flag_open"),
        "ai_flags",
        ["kind", "listing_a", "listing_b"],
        unique=True,
        postgresql_where="((status)::text = 'open'::text)",
        postgresql_nulls_not_distinct=True,
    )
    op.drop_column("ai_flags", "subject")
