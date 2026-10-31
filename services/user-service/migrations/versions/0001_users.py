"""Create users and separate staff credentials."""

import sqlalchemy as sa
from alembic import op

revision = "0001_users"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), unique=True),
        sa.Column("username", sa.String(64)),
        sa.Column("full_name", sa.String(256), nullable=False),
        sa.Column("role", sa.String(7), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("role IN ('CLIENT', 'COOK', 'CASHIER', 'ADMIN')", name="user_role"),
        sa.CheckConstraint("telegram_id IS NULL OR telegram_id > 0", name="positive_telegram_id"),
    )
    op.create_table(
        "staff_credentials",
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("login", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(512), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("staff_credentials")
    op.drop_table("users")
