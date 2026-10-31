import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from order_service.application.schemas import OrderCreate, OrderItemRead, OrderRead
from order_service.config import Settings
from order_service.domain.orders import TRANSITIONS, DishSnapshot, OrderError, OrderStatus
from order_service.infrastructure.database import Database
from order_service.infrastructure.models import (
    ORDER_NUMBER_SEQUENCE,
    IdempotencyRecord,
    Order,
    OrderItem,
    OutboxEvent,
    TimeSlot,
)


class MenuReader(Protocol):
    async def snapshot(self, item_ids: list[UUID]) -> list[DishSnapshot]: ...


def view(order: Order) -> OrderRead:
    return OrderRead(
        id=order.id,
        order_number=order.order_number,
        user_id=order.user_id,
        slot_id=order.slot_id,
        slot_start_time=order.slot.start_time,
        slot_end_time=order.slot.end_time,
        status=order.status,
        total_amount=order.total_amount,
        version=order.version,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=[OrderItemRead.model_validate(item) for item in order.items],
    )


def fingerprint(body: OrderCreate) -> str:
    return hashlib.sha256(
        json.dumps(body.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


async def lock_settings(db: AsyncSession, settings: Settings) -> None:
    await db.execute(
        text("SELECT set_config('lock_timeout', :value, true)"),
        {"value": f"{settings.transaction_lock_timeout_ms}ms"},
    )
    await db.execute(
        text("SELECT set_config('statement_timeout', :value, true)"),
        {"value": f"{settings.transaction_statement_timeout_ms}ms"},
    )


def replay(record: IdempotencyRecord, request_fingerprint: str) -> dict[str, Any]:
    if record.fingerprint != request_fingerprint:
        raise OrderError(
            409, "IDEMPOTENCY_CONFLICT", "This key was used for a different order request"
        )
    if record.response_body is None:
        raise OrderError(
            503, "INCOMPLETE_IDEMPOTENCY_RECORD", "Stored response is unavailable; retry safely"
        )
    return record.response_body


async def existing_response(
    database: Database, user_id: UUID, key: UUID, request_fingerprint: str
) -> dict[str, Any] | None:
    async with database.sessions() as db:
        record = await db.get(IdempotencyRecord, (user_id, key))
        return replay(record, request_fingerprint) if record else None


def outbox(order: Order, event_type: str, previous: OrderStatus | None = None) -> OutboxEvent:
    event_id = uuid4()
    occurred_at = order.updated_at
    payload: dict[str, Any] = {
        "order_number": order.order_number,
        "user_id": str(order.user_id),
        "slot_id": str(order.slot_id),
        "status": order.status.value,
        "total_amount": order.total_amount,
        "order_version": order.version,
    }
    if previous is not None:
        payload["previous_status"] = previous.value
    envelope = {
        "event_id": str(event_id),
        "event_type": event_type,
        "event_version": 1,
        "occurred_at": occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "aggregate_id": str(order.id),
        "payload": payload,
    }
    return OutboxEvent(
        event_id=event_id,
        aggregate_id=order.id,
        aggregate_version=order.version,
        event_type=event_type,
        envelope=envelope,
        occurred_at=occurred_at,
    )


async def create_order(
    database: Database,
    menu: MenuReader,
    settings: Settings,
    user_id: UUID,
    key: UUID,
    body: OrderCreate,
) -> tuple[dict[str, Any], bool]:
    digest = fingerprint(body)
    previous = await existing_response(database, user_id, key, digest)
    if previous is not None:
        return previous, True
    # No database session or transaction is held across the Menu request.
    snapshot_started = time.monotonic()
    try:
        snapshots = await menu.snapshot([line.menu_item_id for line in body.items])
    except OrderError:
        previous = await existing_response(database, user_id, key, digest)
        if previous is not None:
            return previous, True
        raise
    dishes = {dish.id: dish for dish in snapshots}
    if len(dishes) != len(body.items) or set(dishes) != {line.menu_item_id for line in body.items}:
        raise OrderError(503, "INVALID_MENU_SNAPSHOT", "Menu snapshot does not match this request")
    total = sum(dishes[line.menu_item_id].price * line.quantity for line in body.items)
    async with database.sessions() as db, db.begin():
        await lock_settings(db, settings)
        claimed = await db.scalar(
            insert(IdempotencyRecord)
            .values(user_id=user_id, key=key, fingerprint=digest)
            .on_conflict_do_nothing()
            .returning(IdempotencyRecord.key)
        )
        if claimed is None:
            record = await db.get(IdempotencyRecord, (user_id, key))
            if record is None:
                raise OrderError(
                    503, "IDEMPOTENCY_RETRY", "Concurrent request is unavailable; retry safely"
                )
            return replay(record, digest), True
        if total > 2**31 - 1:
            raise OrderError(
                422, "TOTAL_TOO_LARGE", "Order total exceeds the supported integer range"
            )
        if total != body.expected_total_amount:
            raise OrderError(
                409,
                "PRICE_CHANGED",
                "Confirm the current server total before ordering",
                total_amount=total,
            )
        slot = await db.scalar(
            select(TimeSlot).where(TimeSlot.id == body.slot_id).with_for_update()
        )
        if slot is None:
            raise OrderError(404, "SLOT_NOT_FOUND", "Time slot not found")
        if slot.start_time <= datetime.now(UTC):
            raise OrderError(409, "SLOT_CLOSED", "Booking closes when the slot starts")
        if slot.current_orders >= slot.capacity:
            raise OrderError(409, "SLOT_FULL", "Time slot has no remaining capacity")
        if time.monotonic() - snapshot_started > settings.snapshot_max_age_seconds:
            raise OrderError(
                503, "SNAPSHOT_EXPIRED", "Menu snapshot expired while waiting; retry safely"
            )
        slot.current_orders += 1
        number = await db.scalar(select(ORDER_NUMBER_SEQUENCE.next_value()))
        order = Order(
            order_number=f"MAI-{number:06d}",
            user_id=user_id,
            slot_id=slot.id,
            slot=slot,
            status=OrderStatus.PENDING,
            total_amount=total,
            version=1,
            items=[
                OrderItem(
                    menu_item_id=line.menu_item_id,
                    quantity=line.quantity,
                    price_at_moment=dishes[line.menu_item_id].price,
                    name_at_moment=dishes[line.menu_item_id].name,
                )
                for line in body.items
            ],
        )
        db.add(order)
        await db.flush()
        response = view(order).model_dump(mode="json")
        record = await db.get(IdempotencyRecord, (user_id, key))
        assert record is not None
        record.order_id, record.response_body = order.id, response
        db.add(outbox(order, "ORDER_CREATED"))
        # The context commits order/items/capacity/key/response/event together before returning.
    return response, False


async def load_order(db: AsyncSession, order_id: UUID, *, lock: bool = False) -> Order:
    query = (
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items), joinedload(Order.slot))
    )
    if lock:
        query = query.with_for_update(of=Order)
    order = await db.scalar(query)
    if order is None:
        raise OrderError(404, "ORDER_NOT_FOUND", "Order not found")
    return order


def authorize_read(order: Order, user_id: UUID, role: str) -> None:
    if role == "CLIENT" and order.user_id != user_id:
        raise OrderError(404, "ORDER_NOT_FOUND", "Order not found")


async def change_status(
    db: AsyncSession,
    settings: Settings,
    order_id: UUID,
    role: str,
    target: OrderStatus,
    expected_version: int,
) -> OrderRead:
    async with db.begin():
        await lock_settings(db, settings)
        order = await load_order(db, order_id, lock=True)
        if order.version != expected_version:
            raise OrderError(
                409, "VERSION_CONFLICT", "Refresh the order before changing its status"
            )
        transition = TRANSITIONS.get(order.status)
        if target == order.status:
            return view(order)
        if transition is None or transition[0] != target:
            raise OrderError(409, "INVALID_TRANSITION", "This status transition is not allowed")
        if role not in transition[1]:
            raise OrderError(
                403, "ROLE_FORBIDDEN", "This role cannot perform the requested transition"
            )
        previous = order.status
        order.status, order.version, order.updated_at = target, order.version + 1, datetime.now(UTC)
        db.add(outbox(order, "ORDER_STATUS_UPDATED", previous))
        await db.flush()
        return view(order)


async def cancel_order(
    db: AsyncSession,
    settings: Settings,
    order_id: UUID,
    user_id: UUID,
    role: str,
    expected_version: int,
) -> OrderRead:
    async with db.begin():
        await lock_settings(db, settings)
        order = await load_order(db, order_id, lock=True)
        authorize_read(order, user_id, role)
        if role not in {"CLIENT", "ADMIN"}:
            raise OrderError(403, "ROLE_FORBIDDEN", "Only the owner or an administrator can cancel")
        if order.status == OrderStatus.CANCELLED:
            return view(order)
        if order.version != expected_version:
            raise OrderError(409, "VERSION_CONFLICT", "Refresh the order before cancelling")
        allowed = (
            {OrderStatus.PENDING, OrderStatus.PREPARING}
            if role == "ADMIN"
            else {OrderStatus.PENDING}
        )
        if order.status not in allowed:
            raise OrderError(409, "CANNOT_CANCEL", "This order can no longer be cancelled")
        slot = await db.scalar(
            select(TimeSlot)
            .where(TimeSlot.id == order.slot_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        assert slot is not None
        if slot.start_time <= datetime.now(UTC):
            raise OrderError(409, "SLOT_STARTED", "Cancellation closes when the slot starts")
        previous = order.status
        slot.current_orders -= 1
        order.status, order.version, order.updated_at = (
            OrderStatus.CANCELLED,
            order.version + 1,
            datetime.now(UTC),
        )
        db.add(outbox(order, "ORDER_CANCELLED", previous))
        await db.flush()
        return view(order)
