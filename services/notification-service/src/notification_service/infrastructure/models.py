from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Checkpoint(Base):
    __tablename__ = "source_checkpoints"
    __table_args__ = (
        CheckConstraint("partition >= 0 AND next_offset >= 0", name="checkpoint_bounds"),
    )
    group_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    topic: Mapped[str] = mapped_column(String(249), primary_key=True)
    partition: Mapped[int] = mapped_column(primary_key=True)
    next_offset: Mapped[int] = mapped_column(BigInteger)


class Receipt(Base):
    __tablename__ = "source_receipts"
    group_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    topic: Mapped[str] = mapped_column(String(249), primary_key=True)
    partition: Mapped[int] = mapped_column(primary_key=True)
    offset: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    value_hash: Mapped[str] = mapped_column(String(64))
    event_id: Mapped[UUID | None]
    outcome: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(String(32))
    protected_value: Mapped[bytes | None] = mapped_column(LargeBinary)
    truncated: Mapped[bool] = mapped_column(default=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Inbox(Base):
    __tablename__ = "notification_inbox"
    event_id: Mapped[UUID] = mapped_column(primary_key=True)
    order_id: Mapped[UUID]
    content_hash: Mapped[str] = mapped_column(String(64))
    envelope: Mapped[dict[str, Any]] = mapped_column(JSONB)
    outcome: Mapped[str] = mapped_column(String(32))


class OrderObservation(Base):
    __tablename__ = "order_observations"
    order_id: Mapped[UUID] = mapped_column(primary_key=True)
    identity_hash: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[UUID]
    version: Mapped[int]
    status: Mapped[str]
    frozen: Mapped[bool] = mapped_column(default=False)
    gap_observed: Mapped[bool] = mapped_column(default=False)


class ObservedVersion(Base):
    __tablename__ = "observed_versions"
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("order_observations.order_id", ondelete="RESTRICT"), primary_key=True
    )
    version: Mapped[int] = mapped_column(primary_key=True)
    state_hash: Mapped[str] = mapped_column(String(64))
    envelope: Mapped[dict[str, Any]] = mapped_column(JSONB)


class Obligation(Base):
    __tablename__ = "ready_obligations"
    __table_args__ = (
        CheckConstraint("state IN ('PENDING','SUPPRESSED','FROZEN')", name="obligation_state"),
    )
    order_id: Mapped[UUID] = mapped_column(
        ForeignKey("order_observations.order_id", ondelete="RESTRICT"), primary_key=True
    )
    version: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[UUID] = mapped_column(
        ForeignKey("notification_inbox.event_id", ondelete="RESTRICT")
    )
    user_id: Mapped[UUID]
    state: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
