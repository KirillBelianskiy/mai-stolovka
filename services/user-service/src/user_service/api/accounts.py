import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response, status
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
from user_service.infrastructure.models import StaffCredential, User, UserSession

router = APIRouter(tags=["accounts"])
SESSION_COOKIE = "mai_session"
SESSION_COOKIE_PATH = "/api/v1/users/auth"
SESSION_IDLE_DAYS = 30
SESSION_ABSOLUTE_DAYS = 90


def require_session_origin(
    request: Request, origin: Annotated[str | None, Header()] = None
) -> None:
    if origin is None or origin not in request.app.state.settings.allowed_session_origins:
        raise HTTPException(403, "Origin is not allowed")


def session_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def set_session_cookie(response: Response, token: str, absolute_expiry: datetime) -> None:
    remaining = max(0, int((absolute_expiry - datetime.now(UTC)).total_seconds()))
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=remaining,
        expires=absolute_expiry,
        path=SESSION_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=SESSION_COOKIE,
        path=SESSION_COOKIE_PATH,
        secure=True,
        httponly=True,
        samesite="strict",
    )


async def revoke_presented_session(db: LoginSession, token: str | None) -> None:
    if db is None or not token:
        return
    row = await db.scalar(
        select(UserSession)
        .where(UserSession.token_hash == session_token_hash(token))
        .with_for_update()
    )
    if row is not None and row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)


def login_response(request: Request, user: User) -> LoginResponse:
    return LoginResponse(
        access_token=request.app.state.tokens.issue(user.id, user.role),
        expires_in=request.app.state.settings.access_token_ttl_seconds,
        user=UserProfile.model_validate(user),
    )


SessionOrigin = Annotated[None, Depends(require_session_origin)]


def signing_ready(request: Request) -> None:
    if request.app.state.tokens.private_key is None:
        raise HTTPException(503, "Authentication is not configured")


@router.post(
    "/auth/telegram",
    response_model=LoginResponse,
    description=(
        "Validates fresh Telegram initData, creates a revocable browser session, and sets the "
        "Secure, HttpOnly mai_session cookie. Requires an allowlisted Origin."
    ),
)
async def telegram_login(
    body: TelegramLogin,
    request: Request,
    response: Response,
    db: LoginSession,
    _origin: SessionOrigin,
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
    await revoke_presented_session(db, request.cookies.get(SESSION_COOKIE))
    now = datetime.now(UTC)
    absolute_expiry = now + timedelta(days=SESSION_ABSOLUTE_DAYS)
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user.id,
            token_hash=session_token_hash(token),
            last_used_at=now,
            idle_expires_at=now + timedelta(days=SESSION_IDLE_DAYS),
            absolute_expires_at=absolute_expiry,
        )
    )
    result = login_response(request, user)
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    set_session_cookie(response, token, absolute_expiry)
    return result


@router.post(
    "/auth/session",
    response_model=LoginResponse,
    description=(
        "Restores the Mini App identity from the mai_session cookie and issues a fresh access "
        "JWT. Requires an allowlisted Origin."
    ),
)
async def restore_session(
    request: Request,
    response: Response,
    db: LoginSession,
    _origin: SessionOrigin,
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> LoginResponse:
    signing_ready(request)
    if db is None:
        raise HTTPException(503, "Database is unavailable")
    if not token:
        raise HTTPException(401, "Session is not valid")
    session = await db.scalar(
        select(UserSession)
        .where(UserSession.token_hash == session_token_hash(token))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if (
        session is None
        or session.revoked_at is not None
        or session.idle_expires_at <= now
        or session.absolute_expires_at <= now
    ):
        raise HTTPException(401, "Session is not valid")
    user = await db.get(User, session.user_id)
    if user is None or user.role != Role.CLIENT:
        raise HTTPException(401, "Session is not valid")
    session.last_used_at = now
    session.idle_expires_at = min(
        now + timedelta(days=SESSION_IDLE_DAYS), session.absolute_expires_at
    )
    result = login_response(request, user)
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    set_session_cookie(response, token, session.absolute_expires_at)
    return result


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    description=(
        "Revokes the presented Mini App session when present and clears its cookie. Requires "
        "an allowlisted Origin. Existing access JWTs remain valid until expiry."
    ),
)
async def logout(
    request: Request,
    response: Response,
    db: LoginSession,
    _origin: SessionOrigin,
    token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> Response:
    if db is None:
        raise HTTPException(503, "Database is unavailable")
    await revoke_presented_session(db, token)
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    clear_session_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


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
    result = login_response(request, user)
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
