from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from order_service.application.schemas import MAX_INTEGER
from order_service.domain.orders import OrderError
from order_service.infrastructure.models import DishStock, OrderItem


async def lock_stock(db: AsyncSession, item_ids: list[UUID]) -> list[DishStock]:
    if not item_ids:
        return []
    # A row also represents unlimited stock, so configuring an item and ordering it serialize.
    await db.execute(
        insert(DishStock)
        .values([{"menu_item_id": item_id} for item_id in sorted(item_ids)])
        .on_conflict_do_nothing()
    )
    return list(
        await db.scalars(
            select(DishStock)
            .where(DishStock.menu_item_id.in_(item_ids))
            .order_by(DishStock.menu_item_id)
            .with_for_update()
        )
    )


async def reserve_stock(db: AsyncSession, quantities: dict[UUID, int]) -> set[UUID]:
    reserved = set()
    for stock in await lock_stock(db, list(quantities)):
        if stock.remaining_quantity is None:
            continue
        quantity = quantities[stock.menu_item_id]
        if stock.remaining_quantity < quantity:
            raise OrderError(
                409, "INSUFFICIENT_STOCK", "One or more dishes have too few portions remaining"
            )
        stock.remaining_quantity -= quantity
        reserved.add(stock.menu_item_id)
    return reserved


async def return_stock(db: AsyncSession, items: list[OrderItem]) -> None:
    quantities = {item.menu_item_id: item.quantity for item in items if item.stock_reserved}
    for stock in await lock_stock(db, list(quantities)):
        if stock.remaining_quantity is not None:
            stock.remaining_quantity += quantities[stock.menu_item_id]


async def stock_on_hand(db: AsyncSession, item_ids: list[UUID]) -> dict[UUID, int]:
    rows = await db.scalars(
        select(DishStock).where(
            DishStock.menu_item_id.in_(item_ids), DishStock.remaining_quantity.is_not(None)
        )
    )
    return {
        row.menu_item_id: min(row.remaining_quantity, MAX_INTEGER)
        for row in rows
        if row.remaining_quantity is not None
    }
