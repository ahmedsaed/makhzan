"""drop suppliers.phone

The contract step for 2b656e4b5adc, which replaced the single `phone` with
`phones` but kept the column because the release serving during that deploy
still selected it. The live release (f9b1f1c) no longer maps it in either the
api or the ingestion image, so nothing that runs while this migrates reads it.

Not reversible in data: the downgrade re-adds `phone` as a nullable column, and
every row comes back null. Nothing ever wrote it (2b656e4b5adc copied any value
into `phones`, which `worker.sources.sync` now rewrites from sources.toml on
every deploy), so there is nothing to restore it from.

Revision ID: 772533d06b60
Revises: 68056d5bce6b
Create Date: 2026-11-13 02:37:46.305302

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "772533d06b60"
down_revision: str | Sequence[str] | None = "68056d5bce6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("suppliers", "phone")


def downgrade() -> None:
    """Downgrade schema: the column only, empty (see the docstring)."""
    op.add_column("suppliers", sa.Column("phone", sa.String(length=40), nullable=True))
