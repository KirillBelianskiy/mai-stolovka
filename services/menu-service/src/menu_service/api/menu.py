from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement

from menu_service.api.dependencies import Claims, Session
from menu_service.api.schemas import (
    CategoryRead,
    CategoryWrite,
    ItemPage,
    ItemRead,
    ItemWrite,
    SnapshotRequest,
    SnapshotResponse,
)
from menu_service.infrastructure.database import Database
from menu_service.infrastructure.models import Category, MenuItem
from menu_service.infrastructure.tokens import AccessClaims

router = APIRouter(tags=["menu"])


async def require_admin(claims: Claims) -> AccessClaims:
    if claims.role != "ADMIN":
        raise HTTPException(403, "Administrator role required")
    return claims


Admin = Annotated[AccessClaims, Depends(require_admin)]


async def commit_change(db: Session) -> None:
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "Change conflicts with current menu data") from None


@router.get("/categories", response_model=list[CategoryRead])
async def categories(db: Session) -> list[Category]:
    return list(await db.scalars(select(Category).order_by(Category.sort_order, Category.id)))


@router.post("/categories", response_model=CategoryRead, status_code=201)
async def create_category(body: CategoryWrite, admin: Admin, db: Session) -> Category:
    category = Category(**body.model_dump())
    db.add(category)
    await commit_change(db)
    return category


@router.put("/categories/{category_id}", response_model=CategoryRead)
async def update_category(
    category_id: UUID, body: CategoryWrite, admin: Admin, db: Session
) -> Category:
    category = await db.get(Category, category_id)
    if category is None:
        raise HTTPException(404, "Category not found")
    category.name, category.sort_order = body.name, body.sort_order
    await commit_change(db)
    return category


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(category_id: UUID, admin: Admin, db: Session) -> Response:
    category = await db.get(Category, category_id)
    if category is None:
        raise HTTPException(404, "Category not found")
    await db.delete(category)
    await commit_change(db)
    return Response(status_code=204)


@router.get("/items", response_model=ItemPage)
async def items(
    db: Session,
    category_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ItemPage:
    filters: list[ColumnElement[bool]] = [MenuItem.is_available.is_(True)]
    if category_id is not None:
        filters.append(MenuItem.category_id == category_id)
    total = await db.scalar(select(func.count()).select_from(MenuItem).where(*filters))
    rows = await db.scalars(
        select(MenuItem)
        .where(*filters)
        .order_by(MenuItem.name, MenuItem.id)
        .limit(limit)
        .offset(offset)
    )
    return ItemPage(
        items=[ItemRead.model_validate(row) for row in rows],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.get("/admin/items", response_model=ItemPage)
async def admin_items(
    admin: Admin,
    db: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ItemPage:
    total = await db.scalar(select(func.count()).select_from(MenuItem))
    rows = await db.scalars(
        select(MenuItem).order_by(MenuItem.name, MenuItem.id).limit(limit).offset(offset)
    )
    return ItemPage(
        items=[ItemRead.model_validate(row) for row in rows],
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.get("/items/{item_id}", response_model=ItemRead)
async def item(item_id: UUID, db: Session) -> MenuItem:
    current = await db.get(MenuItem, item_id)
    if current is None or not current.is_available:
        raise HTTPException(404, "Menu item not found")
    return current


@router.post("/items", response_model=ItemRead, status_code=201)
async def create_item(body: ItemWrite, admin: Admin, db: Session) -> MenuItem:
    current = MenuItem(**body.model_dump())
    db.add(current)
    await commit_change(db)
    return current


@router.put("/items/{item_id}", response_model=ItemRead)
async def update_item(item_id: UUID, body: ItemWrite, admin: Admin, db: Session) -> MenuItem:
    current = await db.get(MenuItem, item_id)
    if current is None:
        raise HTTPException(404, "Menu item not found")
    for key, value in body.model_dump().items():
        setattr(current, key, value)
    await commit_change(db)
    return current


@router.delete("/items/{item_id}", status_code=204)
async def delete_item(item_id: UUID, admin: Admin, db: Session) -> Response:
    current = await db.get(MenuItem, item_id)
    if current is None:
        raise HTTPException(404, "Menu item not found")
    await db.delete(current)
    await commit_change(db)
    return Response(status_code=204)


@router.post("/item-snapshots", response_model=SnapshotResponse)
async def snapshot(body: SnapshotRequest, request: Request) -> SnapshotResponse:
    database: Database | None = request.app.state.database
    if database is None:
        raise HTTPException(503, "Database is unavailable")
    async with database.sessions() as db:
        rows = list(
            await db.scalars(
                select(MenuItem)
                .where(MenuItem.id.in_(body.item_ids), MenuItem.is_available.is_(True))
                .order_by(MenuItem.id)
            )
        )
        if len(rows) != len(body.item_ids):
            raise HTTPException(
                409, {"code": "ITEM_UNAVAILABLE", "message": "One or more dishes are unavailable"}
            )
        return SnapshotResponse(items=[ItemRead.model_validate(row) for row in rows])
