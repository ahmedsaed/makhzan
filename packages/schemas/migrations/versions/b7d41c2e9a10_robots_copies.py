"""robots copies

`robots_copies`: the last robots.txt the crawler read successfully from each
host. When a host's robots.txt then fails (5xx, 429, timeout), the crawler
uses this copy for up to 30 days instead of refusing the host (RFC 9309
§2.3.1.4). It was kept in the worker's memory only, so a deploy forgot it and
the next blip cost the source its day. Written by the worker on every
successful fetch; empty until then.

Revision ID: b7d41c2e9a10
Revises: 32ed14ef673e
Create Date: 2026-11-10 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7d41c2e9a10"
down_revision: Union[str, Sequence[str], None] = "32ed14ef673e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "robots_copies",
        sa.Column("host", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("host"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("robots_copies")
