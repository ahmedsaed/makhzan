"""supplier contact and source cycle data

`suppliers.contact`: how to reach the shop as the shop itself publishes it (its
LocalBusiness JSON-LD), with where and when it was read. Separate from the
hand-entered address and phone columns, which it never overwrites.

`sources.cycle_data`: a source's per-cycle reference data (category tree,
variant prices, quantity breaks, contact), fetched once at the start of a cycle
and shared by every run of it.

Both nullable with no backfill: an empty value means "not fetched yet".

Revision ID: 1c1a5f0ed0dc
Revises: 753bfc646b85
Create Date: 2026-11-08 22:36:16.840918

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "1c1a5f0ed0dc"
down_revision: Union[str, Sequence[str], None] = "753bfc646b85"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "sources",
        sa.Column("cycle_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "suppliers",
        sa.Column("contact", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("suppliers", "contact")
    op.drop_column("sources", "cycle_data")
