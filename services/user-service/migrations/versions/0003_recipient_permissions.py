"""Persist User-owned Telegram recipient permissions and webhook deduplication."""

import sqlalchemy as sa
from alembic import op

revision = "0003_recipient_permissions"
down_revision = "0002_user_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_recipient_permissions",
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("state", sa.String(length=7), nullable=False, server_default="unknown"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("observed_at", sa.DateTime(timezone=True)),
        sa.Column("evidence_at", sa.DateTime(timezone=True)),
        sa.Column("evidence_kind", sa.String(length=32)),
        sa.CheckConstraint(
            "state IN ('unknown', 'allowed', 'blocked')", name="recipient_permission_state"
        ),
        sa.CheckConstraint("revision >= 0", name="nonnegative_revision"),
    )
    op.create_table(
        "telegram_update_receipts",
        sa.Column("update_id", sa.BigInteger(), primary_key=True),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "recipient_block_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("notification_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("resulting_revision", sa.Integer(), nullable=False),
        sa.Column("resulting_state", sa.String(length=7), nullable=False),
        sa.Column("result_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("notification_id", "reason", name="uq_recipient_block_report_key"),
        sa.CheckConstraint("resulting_revision >= 0", name="nonnegative_result_revision"),
        sa.CheckConstraint("resulting_state = 'blocked'", name="block_report_result_blocked"),
    )
    op.create_index("ix_recipient_block_reports_user_id", "recipient_block_reports", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_recipient_block_reports_user_id", table_name="recipient_block_reports")
    op.drop_table("recipient_block_reports")
    op.drop_table("telegram_update_receipts")
    op.drop_table("telegram_recipient_permissions")
