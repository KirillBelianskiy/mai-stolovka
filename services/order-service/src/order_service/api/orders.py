from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.sql.elements import ColumnElement

from order_service.api.dependencies import Claims, Session
from order_service.application.schemas import (
    OrderCreate,
    OrderPage,
    OrderRead,
    StatusChange,
    VersionInput,
)
from order_service.application.service import (
    authorize_read,
    cancel_order,
    change_status,
    create_order,
    load_order,
    view,
)
from order_service.domain.orders import OrderStatus
from order_service.infrastructure.database import Database
from order_service.infrastructure.models import Order
from order_service.infrastructure.tokens import AccessClaims

router = APIRouter(tags=["orders"])


async def client_only(claims: Claims) -> AccessClaims:
    if claims.role != "CLIENT":
        raise HTTPException(403, "Client role required")
    return claims


async def staff_only(claims: Claims) -> AccessClaims:
    if claims.role == "CLIENT":
        raise HTTPException(403, "Staff role required")
    return claims


Client = Annotated[AccessClaims, Depends(client_only)]
Staff = Annotated[AccessClaims, Depends(staff_only)]


@router.post("/", response_model=OrderRead, status_code=201)
async def create(
    client: Client,
    body: OrderCreate,
    request: Request,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    database: Database | None = request.app.state.database
    if database is None:
        raise HTTPException(503, "Database is unavailable")
    result, replayed = await create_order(
        database,
        request.app.state.menu,
        request.app.state.settings,
        client.sub,
        idempotency_key,
        body,
    )
    return JSONResponse(
        status_code=201,
        content=result,
        headers={"Idempotency-Replayed": str(replayed).lower(), "Cache-Control": "no-store"},
    )


@router.get("/", response_model=OrderPage)
async def history(
    claims: Claims,
    db: Session,
    status: Annotated[list[OrderStatus] | None, Query()] = None,
    slot_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrderPage:
    filters: list[ColumnElement[bool]] = []
    if claims.role == "CLIENT":
        filters.append(Order.user_id == claims.sub)
    if status:
        filters.append(Order.status.in_(status))
    if slot_id:
        filters.append(Order.slot_id == slot_id)
    total = await db.scalar(select(func.count()).select_from(Order).where(*filters))
    rows = await db.scalars(
        select(Order)
        .where(*filters)
        .options(selectinload(Order.items), joinedload(Order.slot))
        .order_by(Order.created_at.desc(), Order.id)
        .limit(limit)
        .offset(offset)
    )
    return OrderPage(
        items=[view(order) for order in rows], total=total or 0, limit=limit, offset=offset
    )


@router.get("/{order_id}", response_model=OrderRead)
async def detail(order_id: UUID, claims: Claims, db: Session) -> OrderRead:
    order = await load_order(db, order_id)
    authorize_read(order, claims.sub, claims.role)
    return view(order)


@router.patch("/{order_id}/status", response_model=OrderRead)
async def update_status(
    order_id: UUID, body: StatusChange, staff: Staff, db: Session, request: Request
) -> OrderRead:
    return await change_status(
        db, request.app.state.settings, order_id, staff.role, body.status, body.expected_version
    )


@router.post("/{order_id}/cancel", response_model=OrderRead)
async def cancel(
    order_id: UUID, body: VersionInput, claims: Claims, db: Session, request: Request
) -> OrderRead:
    return await cancel_order(
        db, request.app.state.settings, order_id, claims.sub, claims.role, body.expected_version
    )
