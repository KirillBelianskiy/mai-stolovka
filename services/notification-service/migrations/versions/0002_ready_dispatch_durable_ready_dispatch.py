"""durable READY dispatch

Revision ID: 0002_ready_dispatch
Revises: 0001_inbox
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_ready_dispatch"
down_revision: str | Sequence[str] | None = "0001_inbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dispatch_bot",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.CheckConstraint("id = 1", name="dispatch_one_bot"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "ready_dispatches",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("notification_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("detail", sa.String(length=32), nullable=True),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("possible_duplicate", sa.Boolean(), nullable=False),
        sa.Column("block_revision", sa.BigInteger(), nullable=True),
        sa.Column("report_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("report_state", sa.String(length=24), nullable=True),
        sa.Column("report_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report_tries", sa.Integer(), nullable=False),
        sa.CheckConstraint("(claim_token IS NULL) = (lease_until IS NULL)", name="dispatch_lease"),
        sa.CheckConstraint("attempt_count BETWEEN 0 AND 8", name="dispatch_attempt_budget"),
        sa.ForeignKeyConstraint(
            ["order_id", "version"],
            ["ready_obligations.order_id", "ready_obligations.version"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("order_id", "version"),
        sa.UniqueConstraint("notification_id"),
    )
    op.create_index(
        "ix_dispatch_active",
        "ready_dispatches",
        ["due_at"],
        unique=False,
        postgresql_where=sa.text("state IN ('waiting','sending')"),
    )
    op.create_index(
        "ix_dispatch_report_due",
        "ready_dispatches",
        ["report_due_at"],
        unique=False,
        postgresql_where=sa.text("report_due_at IS NOT NULL"),
    )
    op.create_table(
        "delivery_attempts",
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("retry_after", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("number BETWEEN 1 AND 8", name="attempt_number_bounds"),
        sa.ForeignKeyConstraint(
            ["order_id", "version"],
            ["ready_dispatches.order_id", "ready_dispatches.version"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("order_id", "version", "number"),
    )
    op.execute(sa.text("INSERT INTO dispatch_bot (id, paused) VALUES (1, false)"))


def downgrade() -> None:
    raise RuntimeError("Dispatch evidence requires a reviewed restore plan")
