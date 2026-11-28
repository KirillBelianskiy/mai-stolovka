"""Store independent menu and detail photos for a dish."""

import sqlalchemy as sa
from alembic import op

revision = "0002_item_photos"
down_revision = "0001_menu"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for kind in ("menu", "detail"):
        op.add_column("menu_items", sa.Column(f"{kind}_photo_version", sa.Uuid()))
        op.add_column("menu_items", sa.Column(f"{kind}_photo", sa.LargeBinary()))


def downgrade() -> None:
    for kind in ("detail", "menu"):
        op.drop_column("menu_items", f"{kind}_photo")
        op.drop_column("menu_items", f"{kind}_photo_version")
