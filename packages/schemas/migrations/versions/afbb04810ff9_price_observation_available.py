"""price observation available

`price_observations.available`: false on the row archiving now writes, so a
listing's history shows the stretch the shop stopped listing it rather than
reading as in stock across it, and a listing coming back at the same price and
stock gets a row dating its return.

Every existing row was written for a listing the source had just seen, so they
are all available: the server default fills them. No archive rows are
backfilled. The table's seed (96e50c11754e) took active listings only, and no
pipeline has archived anything while recording history without this column.

Revision ID: afbb04810ff9
Revises: 56ac7f37b115
Create Date: 2026-11-09 12:17:56.078224

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "afbb04810ff9"
down_revision: Union[str, Sequence[str], None] = "56ac7f37b115"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "price_observations",
        sa.Column("available", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("price_observations", "available")
