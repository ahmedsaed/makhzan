"""drop suppliers.phone

The contract step for 2b656e4b5adc, which replaced the single `phone` with
`phones` but kept the column because the release serving during that deploy
still selected it. The live release (f9b1f1c) no longer maps it in either the
api or the ingestion image, so nothing that runs while this migrates reads it.

The downgrade re-adds `phone` as a nullable column and fills it from the first
entry of `phones` (which 2b656e4b5adc added and which still exists then), as the
old single-number column held. Nothing has written `phone` itself since
2b656e4b5adc copied it into `phones`.

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
    """Downgrade schema: the column back, holding each shop's first number."""
    op.add_column("suppliers", sa.Column("phone", sa.String(length=40), nullable=True))
    op.execute(
        "UPDATE suppliers SET phone = LEFT(phones->>0, 40) "
        "WHERE phones IS NOT NULL AND jsonb_typeof(phones) = 'array' "
        "AND jsonb_array_length(phones) > 0"
    )
