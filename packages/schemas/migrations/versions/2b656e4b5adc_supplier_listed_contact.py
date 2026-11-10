"""supplier listed contact

How to reach a shop, as a person read it off the shop's own pages and entered
it in sources.toml (`worker.sources.sync` writes it on every deploy): email,
the shop's own map link, opening hours, further branches, and where and when
the details were read.

`phone` (one number, never written by anything) becomes `phones`, a list: a
shop with two landlines is common. Any value already there is carried over as
a one-number list, although the next sync rewrites it from the file anyway.

Revision ID: 2b656e4b5adc
Revises: b7d41c2e9a10
Create Date: 2026-11-10 17:23:56.826554

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "2b656e4b5adc"
down_revision: str | Sequence[str] | None = "b7d41c2e9a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("suppliers", sa.Column("phones", postgresql.JSONB(), nullable=True))
    op.add_column("suppliers", sa.Column("email", sa.String(length=254), nullable=True))
    op.add_column("suppliers", sa.Column("maps_url", sa.Text(), nullable=True))
    op.add_column("suppliers", sa.Column("opening_hours", postgresql.JSONB(), nullable=True))
    op.add_column("suppliers", sa.Column("branches", postgresql.JSONB(), nullable=True))
    op.add_column("suppliers", sa.Column("contact_source_url", sa.Text(), nullable=True))
    op.add_column("suppliers", sa.Column("contact_checked_on", sa.Date(), nullable=True))
    op.execute("UPDATE suppliers SET phones = jsonb_build_array(phone) WHERE phone IS NOT NULL")
    op.drop_column("suppliers", "phone")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("suppliers", sa.Column("phone", sa.VARCHAR(length=40), nullable=True))
    # The first number only: the column held one.
    op.execute("UPDATE suppliers SET phone = left(phones ->> 0, 40) WHERE phones IS NOT NULL")
    op.drop_column("suppliers", "contact_checked_on")
    op.drop_column("suppliers", "contact_source_url")
    op.drop_column("suppliers", "branches")
    op.drop_column("suppliers", "opening_hours")
    op.drop_column("suppliers", "maps_url")
    op.drop_column("suppliers", "email")
    op.drop_column("suppliers", "phones")
