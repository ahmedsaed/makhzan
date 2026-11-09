"""permanent product ids

docs/decisions/0004-stable-product-ids.md. A regroup no longer deletes a
product and creates another whenever its group key changes; it keeps the id
and records what happened:

- `products.merged_into` / `merged_at`: the product it was merged into, which
  its URL redirects to. Self-referencing, never pointing at itself.
- `products.delisted_at`: every offer gone; the page says "no longer listed".
- `products.redirect_used_at`, `product_redirects.last_used_at`: when a
  redirect was last followed, so ones unused for a year can be retired
  (docs/decisions/0005-url-retirement.md).
- `product_events`: merge, split, emptied, revived, for audit.
- `products.group_key` is no longer unique: it describes the group a product's
  offers last formed and is not identity. An emptied product keeps its last
  key, and a new product may form the same one.

No data moves. Every product row keeps its id; the first regroup after this
matches each group to the product its listings already point at, so today's
ids stay wherever the grouping agrees. `product_redirects` keeps its rows (ids
deleted before this release), and they keep working.

Downgrade deletes merged-away and emptied products, as the code before this
did, so that `group_key` can be unique again.

Revision ID: 32ed14ef673e
Revises: afbb04810ff9
Create Date: 2026-11-09 12:31:37.793587

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "32ed14ef673e"
down_revision: Union[str, Sequence[str], None] = "afbb04810ff9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "product_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("product_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("MERGE", "SPLIT", "EMPTIED", "REVIVED", name="producteventkind"),
            nullable=False,
        ),
        sa.Column("other_id", sa.UUID(), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_product_event_product_time", "product_events", ["product_id", "created_at"])
    op.create_index(op.f("ix_product_events_other_id"), "product_events", ["other_id"])
    op.add_column(
        "product_redirects", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("products", sa.Column("merged_into", sa.UUID(), nullable=True))
    op.add_column("products", sa.Column("merged_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("products", sa.Column("delisted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "products", sa.Column("redirect_used_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.drop_constraint(op.f("products_group_key_key"), "products", type_="unique")
    op.create_index(op.f("ix_products_group_key"), "products", ["group_key"])
    op.create_index(op.f("ix_products_merged_into"), "products", ["merged_into"])
    op.create_foreign_key(
        "products_merged_into_fkey", "products", "products", ["merged_into"], ["id"]
    )
    op.create_check_constraint(
        "ck_product_not_self", "products", "merged_into IS NULL OR merged_into <> id"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM products WHERE merged_into IS NOT NULL OR delisted_at IS NOT NULL")
    op.drop_constraint("ck_product_not_self", "products", type_="check")
    op.drop_constraint("products_merged_into_fkey", "products", type_="foreignkey")
    op.drop_index(op.f("ix_products_merged_into"), table_name="products")
    op.drop_index(op.f("ix_products_group_key"), table_name="products")
    op.create_unique_constraint(op.f("products_group_key_key"), "products", ["group_key"])
    op.drop_column("products", "redirect_used_at")
    op.drop_column("products", "delisted_at")
    op.drop_column("products", "merged_at")
    op.drop_column("products", "merged_into")
    op.drop_column("product_redirects", "last_used_at")
    op.drop_index(op.f("ix_product_events_other_id"), table_name="product_events")
    op.drop_index("ix_product_event_product_time", table_name="product_events")
    op.drop_table("product_events")
    sa.Enum(name="producteventkind").drop(op.get_bind(), checkfirst=True)
