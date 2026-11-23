"""sources.listed: crawl a shop without showing it

Expand-only. `sources.listed` is sources.toml's `listed` (default true),
rewritten by every sync. False: the source is crawled and stored as usual, but
its listings stay out of grouping, search and every public endpoint, and a
shop only hidden sources name has no page. Every existing row stays listed.

Revision ID: c3f1a7d2b8e4
Revises: 2b9bca910cb2
Create Date: 2026-11-23 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c3f1a7d2b8e4"
down_revision: Union[str, Sequence[str], None] = "2b9bca910cb2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "sources",
        sa.Column("listed", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("sources", "listed")
