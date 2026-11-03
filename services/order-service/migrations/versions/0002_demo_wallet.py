"""Add demo wallet, credit audit and order payment evidence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_demo_wallet"
down_revision = "0001_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("payment_status", sa.String(16), nullable=False, server_default="NOT_REQUIRED"),
    )
    op.create_check_constraint(
        "order_payment_status",
        "orders",
        "payment_status IN ('NOT_REQUIRED','DEMO_PAID','DEMO_REFUNDED')",
    )
    op.create_table(
        "demo_wallets",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("balance", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_credited", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint(
            "balance >= 0 AND balance <= total_credited AND total_credited <= 2147483647",
            name="demo_wallet_bounds",
        ),
    )
    op.create_table(
        "demo_credit_requests",
        sa.Column("key", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
    )
    op.create_table(
        "demo_ledger",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("demo_wallets.user_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(6), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("orders.id", ondelete="RESTRICT")),
        sa.Column(
            "credit_key", sa.Uuid(), sa.ForeignKey("demo_credit_requests.key", ondelete="RESTRICT")
        ),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("amount >= 0", name="demo_ledger_nonnegative_amount"),
        sa.CheckConstraint("kind IN ('CREDIT','DEBIT','REFUND')", name="demo_ledger_kind"),
        sa.CheckConstraint(
            "(kind = 'CREDIT' AND credit_key IS NOT NULL AND order_id IS NULL "
            "AND actor_id IS NOT NULL AND amount > 0) OR "
            "(kind IN ('DEBIT','REFUND') AND order_id IS NOT NULL AND credit_key IS NULL)",
            name="demo_ledger_reference",
        ),
        sa.UniqueConstraint("order_id", "kind", name="demo_order_ledger_once"),
        sa.UniqueConstraint("credit_key", name="demo_credit_ledger_once"),
    )
    op.execute("""
        CREATE FUNCTION reject_demo_ledger_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'Demo ledger is append-only' USING ERRCODE = '23514';
        END;
        $$;
    """)
    op.execute("""
        CREATE TRIGGER demo_ledger_append_only BEFORE UPDATE OR DELETE ON demo_ledger
        FOR EACH ROW EXECUTE FUNCTION reject_demo_ledger_mutation();
    """)


def downgrade() -> None:
    raise RuntimeError("Demo payment evidence must not be discarded; use a reviewed restore plan")
