from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from user_service.domain.users import RecipientPermissionState, Role
from user_service.infrastructure.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("telegram_id IS NULL OR telegram_id > 0", name="positive_telegram_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    telegram_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    username: Mapped[str | None] = mapped_column(String(64))
    full_name: Mapped[str] = mapped_column(String(256))
    role: Mapped[Role] = mapped_column(
        Enum(Role, native_enum=False, create_constraint=True, name="user_role")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StaffCredential(Base):
    __tablename__ = "staff_credentials"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    login: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(512))


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TelegramRecipientPermission(Base):
    __tablename__ = "telegram_recipient_permissions"
    __table_args__ = (CheckConstraint("revision >= 0", name="nonnegative_revision"),)

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[RecipientPermissionState] = mapped_column(
        Enum(
            RecipientPermissionState,
            native_enum=False,
            create_constraint=True,
            name="recipient_permission_state",
            values_callable=lambda enum_type: [item.value for item in enum_type],
        ),
        nullable=False,
        default=RecipientPermissionState.UNKNOWN,
        server_default=RecipientPermissionState.UNKNOWN.value,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    evidence_kind: Mapped[str | None] = mapped_column(String(32))


class TelegramUpdateReceipt(Base):
    __tablename__ = "telegram_update_receipts"

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RecipientBlockReport(Base):
    __tablename__ = "recipient_block_reports"
    __table_args__ = (
        UniqueConstraint("notification_id", "reason", name="uq_recipient_block_report_key"),
        CheckConstraint("resulting_state = 'blocked'", name="block_report_result_blocked"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    notification_id: Mapped[UUID] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    resulting_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    resulting_state: Mapped[str] = mapped_column(String(7), nullable=False)
    result_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
