"""Create slot, order, idempotency and Outbox storage."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_orders"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    sa.Sequence("order_number_seq").create(op.get_bind())
    op.create_table(
        "time_slots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("current_orders", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.CheckConstraint("start_time < end_time", name="slot_time_order"),
        sa.CheckConstraint("capacity > 0", name="positive_capacity"),
        sa.CheckConstraint(
            "current_orders >= 0 AND current_orders <= capacity", name="slot_capacity_bounds"
        ),
    )
    op.create_index("ix_time_slots_start_time", "time_slots", ["start_time"])
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("order_number", sa.String(32), nullable=False, unique=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "slot_id",
            sa.Uuid(),
            sa.ForeignKey("time_slots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(9), nullable=False),
        sa.Column("total_amount", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("total_amount >= 0", name="nonnegative_total"),
        sa.CheckConstraint("version > 0", name="positive_order_version"),
        sa.CheckConstraint(
            "status IN ('PENDING','PREPARING','READY','COMPLETED','CANCELLED')", name="order_status"
        ),
    )
    op.create_index("ix_orders_slot_id", "orders", ["slot_id"])
    op.create_index("ix_orders_user_created", "orders", ["user_id", "created_at"])
    op.create_index("ix_orders_status_created", "orders", ["status", "created_at"])
    op.create_table(
        "order_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "order_id", sa.Uuid(), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("menu_item_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price_at_moment", sa.Integer(), nullable=False),
        sa.Column("name_at_moment", sa.String(256), nullable=False),
        sa.CheckConstraint("quantity > 0", name="positive_item_quantity"),
        sa.CheckConstraint("price_at_moment >= 0", name="nonnegative_item_price"),
        sa.UniqueConstraint("order_id", "menu_item_id", name="unique_order_dish"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_table(
        "idempotency_records",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.Uuid(), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("order_id", sa.Uuid(), sa.ForeignKey("orders.id", ondelete="RESTRICT")),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "outbox_events",
        sa.Column("event_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "aggregate_id",
            sa.Uuid(),
            sa.ForeignKey("orders.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("aggregate_version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("envelope", postgresql.JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("aggregate_id", "aggregate_version", name="unique_order_event_version"),
    )
    op.create_index("ix_outbox_events_aggregate_id", "outbox_events", ["aggregate_id"])
    op.create_index("ix_outbox_events_published_at", "outbox_events", ["published_at"])


def downgrade() -> None:
    op.drop_table("outbox_events")
    op.drop_table("idempotency_records")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("time_slots")
    sa.Sequence("order_number_seq").drop(op.get_bind())
