"""supplier listed contact

How to reach a shop, as a person read it where the shop's details are
published (its site, its Facebook, its Google Maps listing) and entered it in
sources.toml (`worker.sources.sync` writes it on every deploy): a list of
phones, email, a map link, opening hours, further branches, and
`contact_sources`, where and when each detail was read.

Expand only. `phone` (one number, never written by anything) is replaced by
`phones`, and any value in it is copied over, but the column stays: while
`migrate` runs, the release before this one is still serving, and its ORM
selects `phone` with every supplier. Dropping it here would answer those
requests with 500s for the length of the deploy. The ORM no longer maps it;
a later migration, once no running release does, drops it (docs/ROADMAP.md).

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
    op.add_column("suppliers", sa.Column("contact_sources", postgresql.JSONB(), nullable=True))
    op.execute("UPDATE suppliers SET phones = jsonb_build_array(phone) WHERE phone IS NOT NULL")
    # `phone` is kept on purpose; see the docstring.


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("suppliers", "contact_sources")
    op.drop_column("suppliers", "branches")
    op.drop_column("suppliers", "opening_hours")
    op.drop_column("suppliers", "maps_url")
    op.drop_column("suppliers", "email")
    op.drop_column("suppliers", "phones")
