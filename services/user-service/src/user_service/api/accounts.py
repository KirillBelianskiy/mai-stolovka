from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from starlette.concurrency import run_in_threadpool

from user_service.api.dependencies import Claims, LoginSession, Session
from user_service.api.schemas import (
    LoginResponse,
    ProfileUpdate,
    StaffLogin,
    TelegramLogin,
    UserProfile,
)
from user_service.application.passwords import DUMMY_HASH, password_hash
from user_service.application.telegram import InvalidInitData, validate_init_data
from user_service.domain.users import Role
from user_service.infrastructure.models import StaffCredential, User

router = APIRouter(tags=["accounts"])


def signing_ready(request: Request) -> None:
    if request.app.state.tokens.private_key is None:
        raise HTTPException(503, "Authentication is not configured")


@router.post("/auth/telegram", response_model=LoginResponse)
async def telegram_login(
    body: TelegramLogin, request: Request, response: Response, db: LoginSession
) -> LoginResponse:
    signing_ready(request)
    if db is None:
        raise HTTPException(503, "Database is unavailable")
    settings = request.app.state.settings
    if not settings.telegram_bot_token:
        raise HTTPException(503, "Authentication is not configured")
    try:
        identity = validate_init_data(
            body.init_data,
            settings.telegram_bot_token.get_secret_value(),
            max_age=settings.telegram_init_data_max_age_seconds,
        )
    except InvalidInitData:
        raise HTTPException(401, "Invalid Telegram authentication data") from None
    statement = insert(User).values(
        telegram_id=identity.telegram_id,
        username=identity.username,
        full_name=identity.full_name,
        role=Role.CLIENT,
    )
    upsert = statement.on_conflict_do_update(
        index_elements=[User.telegram_id],
        set_={"username": statement.excluded.username},
        where=User.role == Role.CLIENT,
    ).returning(User)
    user = (await db.scalars(upsert)).one_or_none()
    if user is None:
        raise HTTPException(403, "Staff must use staff authentication")
    result = LoginResponse(
        access_token=request.app.state.tokens.issue(user.id, user.role),
        expires_in=settings.access_token_ttl_seconds,
        user=UserProfile.model_validate(user),
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/auth/staff", response_model=LoginResponse)
async def staff_login(
    body: StaffLogin, request: Request, response: Response, db: LoginSession
) -> LoginResponse:
    signing_ready(request)
    if db is None:
        raise HTTPException(503, "Database is unavailable")
    row = (
        await db.execute(
            select(StaffCredential, User).join(User).where(StaffCredential.login == body.username)
        )
    ).one_or_none()
    stored = row[0].password_hash if row else DUMMY_HASH
    valid, updated = await run_in_threadpool(
        password_hash.verify_and_update, body.password.get_secret_value(), stored
    )
    if row is None or not valid or row[1].role == Role.CLIENT or row[1].telegram_id is not None:
        raise HTTPException(
            401, "Invalid username or password", headers={"WWW-Authenticate": "Bearer"}
        )
    credential, user = row
    if updated:
        credential.password_hash = updated
    result = LoginResponse(
        access_token=request.app.state.tokens.issue(user.id, user.role),
        expires_in=request.app.state.settings.access_token_ttl_seconds,
        user=UserProfile.model_validate(user),
    )
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return result


async def current_user(claims: Claims, db: Session) -> User:
    user = await db.get(User, claims.sub)
    if user is None or user.role.value != claims.role:
        raise HTTPException(401, "Invalid access token", headers={"WWW-Authenticate": "Bearer"})
    return user


CurrentUser = Annotated[User, Depends(current_user)]


@router.get("/me", response_model=UserProfile)
async def profile(user: CurrentUser, response: Response) -> User:
    response.headers["Cache-Control"] = "no-store"
    return user


@router.patch("/me", response_model=UserProfile)
async def update_profile(
    body: ProfileUpdate, user: CurrentUser, db: Session, response: Response
) -> User:
    response.headers["Cache-Control"] = "no-store"
    user.full_name = body.full_name
    await db.commit()
    return user
