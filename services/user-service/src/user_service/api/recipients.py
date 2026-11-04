import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Annotated, Literal, cast
from uuid import UUID

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from user_service.domain.users import RecipientPermissionState, Role
from user_service.infrastructure.models import (
    RecipientBlockReport,
    TelegramRecipientPermission,
    TelegramUpdateReceipt,
    User,
)
from user_service.infrastructure.service_tokens import (
    NotificationServiceClaims,
    NotificationServiceTokenVerifier,
)

router = APIRouter(tags=["notification recipients"])
service_bearer = HTTPBearer(auto_error=False)


class RecipientSnapshot(BaseModel):
    user_id: UUID
    state: RecipientPermissionState
    telegram_chat_id: int | None
    revision: int
    observed_at: datetime | None
    evidence_kind: str | None


class BlockObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    expected_revision: int = Field(ge=0)
    telegram_user_id: int = Field(gt=0, le=2**63 - 1)
    notification_id: UUID
    reason: Literal["bot_forbidden", "private_chat_blocked"]


class TelegramWebhookUser(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    id: int = Field(gt=0, le=2**63 - 1)


class TelegramWebhookChat(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    id: int = Field(gt=0, le=2**63 - 1)
    type: str


class TelegramWebhookMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    sender: TelegramWebhookUser | None = Field(default=None, alias="from")
    chat: TelegramWebhookChat
    date: int = Field(gt=0)
    write_access_allowed: dict[str, object] | None = None


class TelegramWebhookUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)

    update_id: int = Field(ge=0, le=2**63 - 1)
    message: TelegramWebhookMessage | None = None


def service_claims(request: Request, authorization: str | None) -> NotificationServiceClaims:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Service authentication required")
    try:
        verifier = cast(NotificationServiceTokenVerifier, request.app.state.notification_tokens)
        claims = verifier.verify(authorization[7:])
    except RuntimeError:
        raise HTTPException(503, "Service authentication is not configured") from None
    except (jwt.PyJWTError, ValidationError, ValueError, TypeError):
        raise HTTPException(401, "Invalid service token") from None
    return claims


async def read_scope(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(service_bearer)],
) -> NotificationServiceClaims:
    claims = service_claims(request, f"Bearer {credentials.credentials}" if credentials else None)
    if "notification:recipient:read" not in claims.scopes:
        raise HTTPException(403, "Insufficient service scope")
    return claims


async def report_scope(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(service_bearer)],
) -> NotificationServiceClaims:
    claims = service_claims(request, f"Bearer {credentials.credentials}" if credentials else None)
    if "notification:permission:report" not in claims.scopes:
        raise HTTPException(403, "Insufficient service scope")
    return claims


async def verify_telegram_webhook(
    request: Request,
    secret: Annotated[str | None, Header(alias="X-Telegram-Bot-Api-Secret-Token")] = None,
) -> None:
    expected = request.app.state.settings.telegram_webhook_secret
    if expected is None:
        raise HTTPException(503, "Telegram webhook authentication is not configured")
    if secret is None or not hmac.compare_digest(secret, expected.get_secret_value()):
        raise HTTPException(403, "Invalid webhook secret")


ReadScope = Annotated[NotificationServiceClaims, Depends(read_scope)]
ReportScope = Annotated[NotificationServiceClaims, Depends(report_scope)]
WebhookAuth = Annotated[None, Depends(verify_telegram_webhook)]


def _permission_time(value: int) -> datetime:
    return datetime.fromtimestamp(value, UTC)


async def _grant(
    db: AsyncSession,
    user: User,
    *,
    evidence_at: datetime,
    evidence_kind: str,
) -> None:
    await db.execute(
        insert(TelegramRecipientPermission)
        .values(
            user_id=user.id,
            state=RecipientPermissionState.UNKNOWN,
            revision=0,
        )
        .on_conflict_do_nothing(index_elements=[TelegramRecipientPermission.user_id])
    )
    permission = await db.scalar(
        select(TelegramRecipientPermission)
        .where(TelegramRecipientPermission.user_id == user.id)
        .with_for_update()
    )
    if permission is None:
        raise RuntimeError("Permission row creation failed")
    if permission.evidence_at is not None and evidence_at <= permission.evidence_at:
        return
    if permission.state != RecipientPermissionState.ALLOWED:
        permission.revision += 1
    permission.state = RecipientPermissionState.ALLOWED
    permission.observed_at = datetime.now(UTC)
    permission.evidence_at = evidence_at
    permission.evidence_kind = evidence_kind


async def record_init_data_permission(db: AsyncSession, user: User, auth_date: int) -> None:
    await _grant(
        db,
        user,
        evidence_at=_permission_time(auth_date),
        evidence_kind="verified_init_data",
    )


@router.get(
    "/internal/v1/notification-recipients/{user_id}",
    response_model=RecipientSnapshot,
    dependencies=[Depends(read_scope)],
)
async def resolve_recipient(
    user_id: UUID, request: Request, response: Response
) -> RecipientSnapshot:
    db = request.app.state.database
    if db is None:
        raise HTTPException(503, "Database is unavailable")
    async with db.sessions() as session:
        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(404, detail={"code": "USER_NOT_FOUND"})
        permission = await session.get(TelegramRecipientPermission, user_id)
        identity_available = user.role == Role.CLIENT and user.telegram_id is not None
        state = (
            permission.state
            if permission is not None and identity_available
            else RecipientPermissionState.UNKNOWN
        )
        allowed = state == RecipientPermissionState.ALLOWED
        response.headers["Cache-Control"] = "no-store"
        return RecipientSnapshot(
            user_id=user.id,
            state=state,
            telegram_chat_id=user.telegram_id if allowed else None,
            revision=permission.revision if permission is not None else 0,
            observed_at=permission.observed_at if permission is not None else None,
            evidence_kind=permission.evidence_kind if permission is not None else None,
        )


@router.post(
    "/internal/v1/notification-recipients/{user_id}/blocked",
    response_model=RecipientSnapshot,
    dependencies=[Depends(report_scope)],
)
async def report_block(
    user_id: UUID,
    body: BlockObservation,
    request: Request,
    response: Response,
) -> RecipientSnapshot:
    db = request.app.state.database
    if db is None:
        raise HTTPException(503, "Database is unavailable")
    canonical = json.dumps(
        {
            "expected_revision": body.expected_revision,
            "telegram_user_id": body.telegram_user_id,
            "notification_id": str(body.notification_id),
            "reason": body.reason,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    request_hash = hashlib.sha256(f"{user_id}:{canonical}".encode()).hexdigest()
    async with db.sessions() as session, session.begin():
        existing = await session.scalar(
            select(RecipientBlockReport)
            .where(
                RecipientBlockReport.notification_id == body.notification_id,
                RecipientBlockReport.reason == body.reason,
            )
            .with_for_update()
        )
        if existing is not None:
            if existing.user_id != user_id or existing.request_hash != request_hash:
                raise HTTPException(409, detail={"code": "IDEMPOTENCY_CONFLICT"})
            user = await session.get(User, user_id)
            if user is None:
                raise HTTPException(404, detail={"code": "USER_NOT_FOUND"})
            result = RecipientSnapshot(
                user_id=user.id,
                state=RecipientPermissionState.BLOCKED,
                telegram_chat_id=None,
                revision=existing.resulting_revision,
                observed_at=existing.result_observed_at,
                evidence_kind=existing.reason,
            )
            response.headers["Cache-Control"] = "no-store"
            return result

        user = await session.get(User, user_id)
        if user is None:
            raise HTTPException(404, detail={"code": "USER_NOT_FOUND"})
        if user.role != Role.CLIENT or user.telegram_id != body.telegram_user_id:
            raise HTTPException(409, detail={"code": "IDENTITY_MISMATCH"})
        await session.execute(
            insert(TelegramRecipientPermission)
            .values(
                user_id=user.id,
                state=RecipientPermissionState.UNKNOWN,
                revision=0,
            )
            .on_conflict_do_nothing(index_elements=[TelegramRecipientPermission.user_id])
        )
        permission = await session.scalar(
            select(TelegramRecipientPermission)
            .where(TelegramRecipientPermission.user_id == user_id)
            .with_for_update()
        )
        if permission is None:
            raise RuntimeError("Permission row creation failed")
        existing = await session.scalar(
            select(RecipientBlockReport)
            .where(
                RecipientBlockReport.notification_id == body.notification_id,
                RecipientBlockReport.reason == body.reason,
            )
            .with_for_update()
        )
        if existing is not None:
            if existing.user_id != user_id or existing.request_hash != request_hash:
                raise HTTPException(409, detail={"code": "IDEMPOTENCY_CONFLICT"})
            result = RecipientSnapshot(
                user_id=user.id,
                state=RecipientPermissionState.BLOCKED,
                telegram_chat_id=None,
                revision=existing.resulting_revision,
                observed_at=existing.result_observed_at,
                evidence_kind=existing.reason,
            )
            response.headers["Cache-Control"] = "no-store"
            return result
        if permission.revision != body.expected_revision:
            raise HTTPException(
                409,
                detail={"code": "REVISION_CONFLICT", "revision": permission.revision},
            )
        if permission.state != RecipientPermissionState.BLOCKED:
            permission.revision += 1
        permission.state = RecipientPermissionState.BLOCKED
        permission.observed_at = datetime.now(UTC)
        permission.evidence_at = permission.observed_at
        permission.evidence_kind = body.reason
        session.add(
            RecipientBlockReport(
                user_id=user.id,
                notification_id=body.notification_id,
                reason=body.reason,
                request_hash=request_hash,
                resulting_revision=permission.revision,
                resulting_state=permission.state.value,
                result_observed_at=permission.observed_at,
            )
        )
        result = RecipientSnapshot(
            user_id=user.id,
            state=permission.state,
            telegram_chat_id=None,
            revision=permission.revision,
            observed_at=permission.observed_at,
            evidence_kind=permission.evidence_kind,
        )
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post(
    "/internal/v1/telegram/webhook",
    status_code=204,
    dependencies=[Depends(verify_telegram_webhook)],
)
async def telegram_webhook(
    update: TelegramWebhookUpdate,
    request: Request,
    response: Response,
) -> Response:
    db = request.app.state.database
    if db is None:
        raise HTTPException(503, "Database is unavailable")
    payload = await request.body()
    digest = hashlib.sha256(payload).hexdigest()
    async with db.sessions() as session, session.begin():
        inserted = await session.scalar(
            insert(TelegramUpdateReceipt)
            .values(update_id=update.update_id, payload_hash=digest)
            .on_conflict_do_nothing(index_elements=[TelegramUpdateReceipt.update_id])
            .returning(TelegramUpdateReceipt.update_id)
        )
        if inserted is None:
            prior = await session.get(TelegramUpdateReceipt, update.update_id)
            if prior is None or prior.payload_hash != digest:
                raise HTTPException(409, detail={"code": "UPDATE_ID_CONFLICT"})
        else:
            message = update.message
            if (
                message is not None
                and message.sender is not None
                and message.write_access_allowed is not None
            ):
                if (
                    message.chat.type != "private"
                    or message.chat.id != message.sender.id
                    or message.date > int(datetime.now(UTC).timestamp()) + 30
                ):
                    raise HTTPException(422, detail={"code": "INVALID_PERMISSION_EVIDENCE"})
                user = await session.scalar(
                    select(User).where(
                        User.telegram_id == message.sender.id,
                        User.role == Role.CLIENT,
                    )
                )
                if user is not None:
                    await _grant(
                        session,
                        user,
                        evidence_at=_permission_time(message.date),
                        evidence_kind="write_access_allowed",
                    )
    response.headers["Cache-Control"] = "no-store"
    response.status_code = 204
    return response
