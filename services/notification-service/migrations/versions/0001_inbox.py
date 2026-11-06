"""Durable Notification ingestion and source responsibility."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_inbox"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_checkpoints",
        sa.Column("group_id", sa.String(128), primary_key=True),
        sa.Column("topic", sa.String(249), primary_key=True),
        sa.Column("partition", sa.Integer(), primary_key=True),
        sa.Column("next_offset", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("partition >= 0 AND next_offset >= 0", name="checkpoint_bounds"),
    )
    op.create_table(
        "source_receipts",
        sa.Column("group_id", sa.String(128), primary_key=True),
        sa.Column("topic", sa.String(249), primary_key=True),
        sa.Column("partition", sa.Integer(), primary_key=True),
        sa.Column("offset", sa.BigInteger(), primary_key=True),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("value_hash", sa.String(64), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("reason", sa.String(32), nullable=True),
        sa.Column("protected_value", sa.LargeBinary(), nullable=True),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "notification_inbox",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("envelope", postgresql.JSONB(), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
    )
    op.create_table(
        "order_observations",
        sa.Column("order_id", sa.Uuid(), primary_key=True),
        sa.Column("identity_hash", sa.String(64), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("frozen", sa.Boolean(), nullable=False),
        sa.Column("gap_observed", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "observed_versions",
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("order_observations.order_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("envelope", postgresql.JSONB(), nullable=False),
    )
    op.create_table(
        "ready_obligations",
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("order_observations.order_id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Uuid(),
            sa.ForeignKey("notification_inbox.event_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("state IN ('PENDING','SUPPRESSED','FROZEN')", name="obligation_state"),
    )


def downgrade() -> None:
    raise RuntimeError("Durable notification responsibility requires a reviewed restore plan")
