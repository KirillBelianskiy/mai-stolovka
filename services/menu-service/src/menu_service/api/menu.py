from typing import Annotated
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.elements import ColumnElement
from starlette.concurrency import run_in_threadpool

from menu_service.api.dependencies import Claims, Session
from menu_service.api.schemas import (
    CategoryRead,
    CategoryWrite,
    ItemPage,
    ItemRead,
    ItemWrite,
    SnapshotItem,
    SnapshotRequest,
    SnapshotResponse,
)
from menu_service.application.photos import MAX_PHOTO_BYTES, InvalidPhoto, PhotoKind, prepare_photo
from menu_service.infrastructure.database import Database
from menu_service.infrastructure.models import Category, MenuItem
from menu_service.infrastructure.stock import StockClient
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
async def categories(db: Session) -> list[CategoryRead]:
    counts = (
        select(MenuItem.category_id, func.count().label("published_count"))
        .where(MenuItem.is_available.is_(True))
        .group_by(MenuItem.category_id)
        .subquery()
    )
    rows = await db.execute(
        select(Category, func.coalesce(counts.c.published_count, 0))
        .outerjoin(counts, counts.c.category_id == Category.id)
        .order_by(Category.sort_order, Category.id)
    )
    return [
        CategoryRead.model_validate(category).model_copy(update={"published_item_count": count})
        for category, count in rows
    ]


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


async def read_items(rows: list[MenuItem], request: Request) -> list[ItemRead]:
    stock: StockClient = request.app.state.stock
    counts = await stock.remaining([row.id for row in rows])
    return [
        ItemRead.model_validate(row).model_copy(update={"remaining_quantity": counts.get(row.id)})
        for row in rows
    ]


@router.get("/items", response_model=ItemPage)
async def items(
    request: Request,
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
        items=await read_items(list(rows), request),
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.get("/admin/items", response_model=ItemPage)
async def admin_items(
    request: Request,
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
        items=await read_items(list(rows), request),
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.get("/items/{item_id}", response_model=ItemRead)
async def item(item_id: UUID, db: Session, request: Request) -> ItemRead:
    current = await db.get(MenuItem, item_id)
    if current is None or not current.is_available:
        raise HTTPException(404, "Menu item not found")
    return (await read_items([current], request))[0]


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


async def read_photo(upload: UploadFile, kind: PhotoKind) -> bytes:
    contents = await upload.read(MAX_PHOTO_BYTES + 1)
    if len(contents) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Размер одного фото должен быть не больше 5 МБ.")
    try:
        return await run_in_threadpool(prepare_photo, contents, kind)
    except InvalidPhoto as error:
        raise HTTPException(422, str(error)) from error


async def save_item_with_photos(
    db: Session,
    item_id: UUID | None,
    item_json: str,
    menu_photo: UploadFile | None,
    detail_photo: UploadFile | None,
) -> MenuItem:
    try:
        body = ItemWrite.model_validate_json(item_json)
    except ValidationError as error:
        raise HTTPException(422, "Проверьте название, категорию и цену блюда.") from error

    # Decode both files before taking the row lock. A failed photo leaves the dish untouched.
    menu = await read_photo(menu_photo, "menu") if menu_photo else None
    detail = await read_photo(detail_photo, "detail") if detail_photo else None
    values = body.model_dump(exclude_unset=True)
    current: MenuItem | None
    if item_id is None:
        current = MenuItem(**values)
        db.add(current)
    else:
        current = await db.get(MenuItem, item_id, with_for_update=True)
        if current is None:
            raise HTTPException(404, "Menu item not found")
        for key, value in values.items():
            setattr(current, key, value)

    if menu is not None:
        current.menu_photo, current.menu_photo_version = menu, uuid4()
    if detail is not None:
        current.detail_photo, current.detail_photo_version = detail, uuid4()
    await commit_change(db)
    return current


@router.post("/admin/items/upload", response_model=ItemRead, status_code=201)
async def create_item_with_photos(
    admin: Admin,
    db: Session,
    item_json: Annotated[str, Form(max_length=20000)],
    menu_photo: Annotated[UploadFile, File()],
    detail_photo: Annotated[UploadFile, File()],
) -> MenuItem:
    return await save_item_with_photos(db, None, item_json, menu_photo, detail_photo)


@router.put("/admin/items/{item_id}/upload", response_model=ItemRead)
async def update_item_with_photos(
    item_id: UUID,
    admin: Admin,
    db: Session,
    item_json: Annotated[str, Form(max_length=20000)],
    menu_photo: Annotated[UploadFile | None, File()] = None,
    detail_photo: Annotated[UploadFile | None, File()] = None,
) -> MenuItem:
    return await save_item_with_photos(db, item_id, item_json, menu_photo, detail_photo)


@router.get(
    "/photos/{item_id}/{kind}/{version}",
    response_class=Response,
    responses={200: {"content": {"image/webp": {}}}},
)
async def item_photo(item_id: UUID, kind: PhotoKind, version: UUID, db: Session) -> Response:
    data, revision = (
        (MenuItem.menu_photo, MenuItem.menu_photo_version)
        if kind == "menu"
        else (MenuItem.detail_photo, MenuItem.detail_photo_version)
    )
    photo = await db.scalar(select(data).where(MenuItem.id == item_id, revision == version))
    if photo is None:
        raise HTTPException(404, "Photo not found")
    return Response(
        content=photo,
        media_type="image/webp",
        headers={"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"},
    )


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
        return SnapshotResponse(items=[SnapshotItem.model_validate(row) for row in rows])
