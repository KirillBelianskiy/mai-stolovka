"""Track available portions and the orders that reserved them."""

import sqlalchemy as sa
from alembic import op

revision = "0003_dish_stock"
down_revision = "0002_demo_wallet"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dish_stock",
        sa.Column("menu_item_id", sa.Uuid(), primary_key=True),
        sa.Column("remaining_quantity", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("remaining_quantity >= 0", name="dish_stock_nonnegative"),
    )
    op.add_column(
        "order_items",
        sa.Column("stock_reserved", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("order_items", "stock_reserved")
    op.drop_table("dish_stock")
