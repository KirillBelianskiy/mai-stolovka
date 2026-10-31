from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Sequence,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from order_service.domain.orders import OrderStatus
from order_service.infrastructure.database import Base

ORDER_NUMBER_SEQUENCE = Sequence("order_number_seq", metadata=Base.metadata)


class TimeSlot(Base):
    __tablename__ = "time_slots"
    __table_args__ = (
        CheckConstraint("start_time < end_time", name="slot_time_order"),
        CheckConstraint("capacity > 0", name="positive_capacity"),
        CheckConstraint(
            "current_orders >= 0 AND current_orders <= capacity", name="slot_capacity_bounds"
        ),
        Index("ix_time_slots_start_time", "start_time"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    capacity: Mapped[int]
    current_orders: Mapped[int] = mapped_column(default=0, server_default=text("0"))


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="nonnegative_total"),
        CheckConstraint("version > 0", name="positive_order_version"),
        Index("ix_orders_user_created", "user_id", "created_at"),
        Index("ix_orders_status_created", "status", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    order_number: Mapped[str] = mapped_column(String(32), unique=True)
    user_id: Mapped[UUID]
    slot_id: Mapped[UUID] = mapped_column(
        ForeignKey("time_slots.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, native_enum=False, create_constraint=True, name="order_status")
    )
    total_amount: Mapped[int]
    version: Mapped[int] = mapped_column(default=1, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    items: Mapped[list[OrderItem]] = relationship(
        cascade="all, delete-orphan", lazy="raise", order_by="OrderItem.menu_item_id"
    )
    slot: Mapped[TimeSlot] = relationship(lazy="raise")


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="positive_item_quantity"),
        CheckConstraint("price_at_moment >= 0", name="nonnegative_item_price"),
        UniqueConstraint("order_id", "menu_item_id", name="unique_order_dish"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    menu_item_id: Mapped[UUID]
    quantity: Mapped[int]
    price_at_moment: Mapped[int]
    name_at_moment: Mapped[str] = mapped_column(String(256))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    user_id: Mapped[UUID] = mapped_column(primary_key=True)
    key: Mapped[UUID] = mapped_column(primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[UUID | None] = mapped_column(ForeignKey("orders.id", ondelete="RESTRICT"))
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("aggregate_id", "aggregate_version", name="unique_order_event_version"),
    )
    event_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    aggregate_id: Mapped[UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), index=True
    )
    aggregate_version: Mapped[int]
    event_type: Mapped[str] = mapped_column(String(32))
    envelope: Mapped[dict[str, Any]] = mapped_column(JSONB)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
