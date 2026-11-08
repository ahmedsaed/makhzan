"""listing last seen at

`listings.last_seen_at`: when the source last said the listing exists, by any
route. Archiving keys off it instead of `last_verified_at`, which now means only
"price and details last read" — a shop that lists an out-of-stock product by id
alone keeps it alive without re-stating its price.

Backfilled from `last_verified_at`, which is what archiving read until now. A
plain `now()` default would make every listing look seen at deploy time, and the
cycle in flight would then archive nothing it should.

Revision ID: ff12e5d80480
Revises: 1c1a5f0ed0dc
Create Date: 2026-11-09 00:09:43.025570

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "ff12e5d80480"
down_revision: Union[str, Sequence[str], None] = "1c1a5f0ed0dc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("listings", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE listings SET last_seen_at = last_verified_at")
    op.alter_column("listings", "last_seen_at", nullable=False, server_default=sa.text("now()"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("listings", "last_seen_at")
