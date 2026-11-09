"""price observations

`price_observations`: a listing's price and stock at each point they changed.
Every crawl overwrites `listings.price` and `stock_signal`, so the history behind
"lowest in 90 days" or "in stock N of the last 12 weeks" is lost as it happens
and can never be backfilled. The pipeline now writes a row when a listing is
first stored and whenever its price, currency or stock signal changes.

Seeded with one row per active listing, at its current values and as of its
`last_verified_at` (when they were last read), so every history starts from a
baseline rather than from the first change after this deploy. Archived, hidden
and review listings are left out: their values are not current, and the
pipeline writes a first row for any of them that comes back.

`stocksignal` already exists (it types `listings.stock_signal`), so the column
reuses it rather than creating it again.

Revision ID: 96e50c11754e
Revises: ff12e5d80480
Create Date: 2026-11-09 11:11:21.105335

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "96e50c11754e"
down_revision: Union[str, Sequence[str], None] = "ff12e5d80480"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "price_observations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("listing_id", sa.UUID(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "stock_signal",
            postgresql.ENUM(name="stocksignal", create_type=False),
            nullable=False,
        ),
        sa.Column("in_stock", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_price_observation_listing_time",
        "price_observations",
        ["listing_id", "observed_at"],
        unique=False,
    )
    op.execute(
        """
        INSERT INTO price_observations
            (id, listing_id, observed_at, price, currency, stock_signal, in_stock)
        SELECT gen_random_uuid(), id, last_verified_at, price, currency, stock_signal,
               stock_signal = 'IN_STOCK'
        FROM listings
        WHERE status = 'ACTIVE'
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_price_observation_listing_time", table_name="price_observations")
    op.drop_table("price_observations")
