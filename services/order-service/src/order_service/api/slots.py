from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select

from order_service.api.dependencies import Claims, Session
from order_service.application.schemas import SlotRead, SlotWrite
from order_service.application.service import lock_settings
from order_service.domain.orders import OrderError
from order_service.infrastructure.models import Order, TimeSlot
from order_service.infrastructure.tokens import AccessClaims

router = APIRouter(prefix="/slots", tags=["slots"])


async def admin_only(claims: Claims) -> AccessClaims:
    if claims.role != "ADMIN":
        raise HTTPException(403, "Administrator role required")
    return claims


Admin = Annotated[AccessClaims, Depends(admin_only)]


@router.get("", response_model=list[SlotRead])
async def available_slots(
    claims: Claims,
    db: Session,
    include_past: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SlotRead]:
    if include_past and claims.role == "CLIENT":
        raise HTTPException(403, "Staff role required for past slots")
    query = select(TimeSlot)
    if not include_past:
        query = query.where(TimeSlot.start_time > datetime.now(UTC))
    rows = await db.scalars(
        query.order_by(TimeSlot.start_time, TimeSlot.id).limit(limit).offset(offset)
    )
    return [SlotRead.model_validate(slot) for slot in rows]


@router.post("", response_model=SlotRead, status_code=201)
async def create_slot(admin: Admin, body: SlotWrite, db: Session) -> TimeSlot:
    if body.start_time <= datetime.now(UTC):
        raise OrderError(409, "SLOT_STARTED", "New slots must start in the future")
    async with db.begin():
        slot = TimeSlot(**body.model_dump())
        db.add(slot)
        await db.flush()
        return slot


@router.put("/{slot_id}", response_model=SlotRead)
async def update_slot(
    slot_id: UUID, admin: Admin, body: SlotWrite, db: Session, request: Request
) -> TimeSlot:
    async with db.begin():
        await lock_settings(db, request.app.state.settings)
        slot = await db.scalar(select(TimeSlot).where(TimeSlot.id == slot_id).with_for_update())
        if slot is None:
            raise OrderError(404, "SLOT_NOT_FOUND", "Time slot not found")
        if body.capacity < slot.current_orders:
            raise OrderError(
                409, "CAPACITY_CONFLICT", "Capacity cannot be lower than reserved orders"
            )
        has_orders = await db.scalar(select(Order.id).where(Order.slot_id == slot_id).limit(1))
        changed_times = slot.start_time != body.start_time or slot.end_time != body.end_time
        if has_orders and changed_times:
            raise OrderError(
                409, "SLOT_HAS_ORDERS", "Times cannot change after an order references this slot"
            )
        if changed_times and body.start_time <= datetime.now(UTC):
            raise OrderError(409, "SLOT_STARTED", "New slot times must start in the future")
        slot.start_time, slot.end_time, slot.capacity = (
            body.start_time,
            body.end_time,
            body.capacity,
        )
        await db.flush()
        return slot


@router.delete("/{slot_id}", status_code=204)
async def delete_slot(slot_id: UUID, admin: Admin, db: Session, request: Request) -> Response:
    async with db.begin():
        await lock_settings(db, request.app.state.settings)
        slot = await db.scalar(select(TimeSlot).where(TimeSlot.id == slot_id).with_for_update())
        if slot is None:
            raise OrderError(404, "SLOT_NOT_FOUND", "Time slot not found")
        if await db.scalar(select(Order.id).where(Order.slot_id == slot_id).limit(1)):
            raise OrderError(
                409, "SLOT_HAS_ORDERS", "A slot referenced by order history cannot be deleted"
            )
        await db.delete(slot)
    return Response(status_code=204)
