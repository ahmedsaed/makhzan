"""products.image_supplier_id

Which shop a product's photo (`products.image`) comes from, so every place the
photo is shown can credit that shop with a badge. Set by the product rebuild
alongside `image`; null until the first rebuild after this migration, and the
site shows no badge while it is.

Expand only: a nullable column the release still serving during the deploy
does not know about and never selects. Autogenerate also proposed dropping
`suppliers.phone`; that column is kept on purpose (see 2b656e4b5adc) and the
drop was removed by hand.

Revision ID: 68056d5bce6b
Revises: 2b656e4b5adc
Create Date: 2026-11-10 19:18:19.251272

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "68056d5bce6b"
down_revision: str | Sequence[str] | None = "2b656e4b5adc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("products", sa.Column("image_supplier_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "products_image_supplier_id_fkey",
        "products",
        "suppliers",
        ["image_supplier_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("products_image_supplier_id_fkey", "products", type_="foreignkey")
    op.drop_column("products", "image_supplier_id")
