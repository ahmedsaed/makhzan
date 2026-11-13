"""products min price details

What the product page and a result row say about the low end of a product's
price range (makhzan_schemas.pricing): the offer and shop setting `min_price`,
the option of it that does, its minimum order, whether the range reads "each",
and how many offers are on request. Set by the product rebuild with
`min_price`; empty (and `price_each` false, `on_request_count` 0) until the
first rebuild after this migration.

Expand only: nullable columns or ones with a server default, which the release
still serving during the deploy neither selects nor has to write. Fails
after 5 s rather than wait for a lock on `products` (a rebuild in progress);
re-run the deploy if it does.
`min_price_listing_id` is deliberately not a foreign key: listings already
point at products, and a second path between the two tables would make the
ORM's joins between them ambiguous.

Revision ID: 2db8f3d44c3c
Revises: 772533d06b60
Create Date: 2026-11-13 12:54:11.127921

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2db8f3d44c3c"
down_revision: str | Sequence[str] | None = "772533d06b60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # ALTER TABLE takes an exclusive lock on products. Behind a long rebuild
    # transaction it would queue, and every API read of products would queue
    # behind it. Fail fast instead: a deploy that times out here changed
    # nothing and only needs re-running. LOCAL: the setting ends with the
    # migration transaction, not with the pooled connection.
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.add_column("products", sa.Column("min_price_listing_id", sa.UUID(), nullable=True))
    op.add_column("products", sa.Column("min_price_supplier_id", sa.UUID(), nullable=True))
    op.add_column("products", sa.Column("min_price_option", sa.String(length=200), nullable=True))
    op.add_column("products", sa.Column("min_price_quantity", sa.Integer(), nullable=True))
    op.add_column(
        "products",
        sa.Column("price_each", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column(
        "products",
        sa.Column("on_request_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_foreign_key(
        "products_min_price_supplier_id_fkey",
        "products",
        "suppliers",
        ["min_price_supplier_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("products_min_price_supplier_id_fkey", "products", type_="foreignkey")
    op.drop_column("products", "on_request_count")
    op.drop_column("products", "price_each")
    op.drop_column("products", "min_price_quantity")
    op.drop_column("products", "min_price_option")
    op.drop_column("products", "min_price_supplier_id")
    op.drop_column("products", "min_price_listing_id")
