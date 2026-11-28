from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from order_service.api.dependencies import Claims, Session
from order_service.application.schemas import MAX_INTEGER
from order_service.application.service import lock_settings
from order_service.application.stock import lock_stock, stock_on_hand
from order_service.infrastructure.tokens import AccessClaims

router = APIRouter(tags=["dish stock"])


class StockCount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    remaining_quantity: int | None = Field(ge=0, le=MAX_INTEGER, strict=True)


class StockLookup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_ids: list[UUID] = Field(min_length=1, max_length=100)


async def require_admin(claims: Claims) -> AccessClaims:
    if claims.role != "ADMIN":
        raise HTTPException(403, "Administrator role required")
    return claims


@router.put("/inventory/{item_id}", response_model=StockCount)
async def set_stock(
    item_id: UUID,
    body: StockCount,
    admin: Annotated[AccessClaims, Depends(require_admin)],
    db: Session,
    request: Request,
) -> StockCount:
    async with db.begin():
        await lock_settings(db, request.app.state.settings)
        (stock,) = await lock_stock(db, [item_id])
        stock.remaining_quantity = body.remaining_quantity
    return body


@router.post("/internal/menu-stock", response_model=dict[UUID, int], include_in_schema=False)
async def lookup(body: StockLookup, db: Session) -> dict[UUID, int]:
    return await stock_on_hand(db, body.item_ids)
