"""add product content_changed_at

When what a reader sees of a product last changed: the sitemap's lastmod.

Existing rows have no history to read it from, so they start at their last
verification (the newest evidence the content was as it is), falling back to
the row's own update time. Added nullable, backfilled, then made NOT NULL with
the default new rows take.

Revision ID: 753bfc646b85
Revises: 73784d7c4fca
Create Date: 2026-11-08 20:49:18.036740

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "753bfc646b85"
down_revision: Union[str, Sequence[str], None] = "73784d7c4fca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "products",
        sa.Column("content_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE products SET content_changed_at = coalesce(last_verified_at, updated_at, now())"
    )
    op.alter_column(
        "products",
        "content_changed_at",
        nullable=False,
        server_default=sa.text("now()"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("products", "content_changed_at")
