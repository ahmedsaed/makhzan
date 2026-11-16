"""product representative listing

`products.representative_listing_id`: the listing the regroup took the
product's title, brand, category and domain from (grouping._representative).
The product page's shop view picks it on a plain load, so the h1 and <title>
name the same listing (owner decision, November 2026).

Expand-only and nullable. Not a foreign key, like `min_price_listing_id`:
listings already point at products, and a second path between the tables
would make their joins ambiguous. Existing rows stay null until the next
rebuild sets them; until then the API finds the same listing by the same rule
over the product's current offers.

Revision ID: 96d1051aab62
Revises: a21d405bb303
Create Date: 2026-11-16 23:27:32.324251

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "96d1051aab62"
down_revision: str | Sequence[str] | None = "a21d405bb303"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("products", sa.Column("representative_listing_id", sa.UUID(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("products", "representative_listing_id")
