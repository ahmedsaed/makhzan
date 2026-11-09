"""worker state

`worker_state`: what the running worker believes, stated by it at startup, for
the API to report. The first key is `crawl` (`{"enabled": bool}`): the API used
to read `CRAWL_ENABLED` from its own environment, and `./makhzan crawl off`
recreates only the worker, so /how-we-crawl kept announcing a next run that
would never happen. Empty until a worker starts; the API falls back to its
environment until then.

Revision ID: 56ac7f37b115
Revises: 96e50c11754e
Create Date: 2026-11-09 12:15:09.671847

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "56ac7f37b115"
down_revision: Union[str, Sequence[str], None] = "96e50c11754e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "worker_state",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("worker_state")
