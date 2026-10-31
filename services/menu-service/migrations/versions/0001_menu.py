"""Create categories and menu items."""

import sqlalchemy as sa
from alembic import op

revision = "0001_menu"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
    )
    op.create_table(
        "menu_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "category_id",
            sa.Uuid(),
            sa.ForeignKey("categories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("image_url", sa.String(2048)),
        sa.Column("is_available", sa.Boolean(), nullable=False),
        sa.CheckConstraint("price >= 0", name="nonnegative_price"),
    )
    op.create_index("ix_menu_items_category_id", "menu_items", ["category_id"])


def downgrade() -> None:
    op.drop_table("menu_items")
    op.drop_table("categories")
