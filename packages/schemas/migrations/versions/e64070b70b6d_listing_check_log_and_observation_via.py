"""listing check log and observation via

The check log of the crawler scheduling plan (Phase 0, T7): per listing, how
many times its price and stock were read (`checks`), how many of those reads
found them changed (`changes`), between when (`first_checked_at`,
`last_checked_at`). That is what estimating a change rate needs;
`price_observations` cannot give it, because a re-read that finds nothing new
writes no row there.

`price_observations.via` names the kind of read that wrote a row, so changes
found per request can later be split by lane. Every existing row came from the
sweep (or the archiving that closes one), so the server default is true of
them all. `price_observations.prev_checked_at` is the listing's previous read
when a row was written, which dates how late the change was found (M5).

Expand-safe: only new columns, each nullable or with a constant server default,
which Postgres adds without rewriting the table. A release that predates them
keeps working while this runs: it never names them, and its inserts take the
defaults. Nothing is backfilled: existing listings start at 0 checks with no
`first_checked_at`, and count from their next read.

Revision ID: e64070b70b6d
Revises: 772533d06b60
Create Date: 2026-11-13 12:51:43.410849

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e64070b70b6d"
down_revision: Union[str, Sequence[str], None] = "772533d06b60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("listings", sa.Column("checks", sa.Integer(), server_default="0", nullable=False))
    op.add_column(
        "listings", sa.Column("changes", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "listings", sa.Column("first_checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "listings", sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "price_observations",
        sa.Column("via", sa.String(length=16), server_default="sweep", nullable=False),
    )
    op.add_column(
        "price_observations",
        sa.Column("prev_checked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("price_observations", "prev_checked_at")
    op.drop_column("price_observations", "via")
    op.drop_column("listings", "last_checked_at")
    op.drop_column("listings", "first_checked_at")
    op.drop_column("listings", "changes")
    op.drop_column("listings", "checks")
