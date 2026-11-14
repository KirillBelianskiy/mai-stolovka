import asyncio
import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from notification_service.config import Settings
from notification_service.domain.delivery import (
    NETWORK_TIMEOUT,
    BlockReport,
    DeliveryResult,
    Recipient,
    ReportResult,
)

READ_SCOPE = "notification:recipient:read"
REPORT_SCOPE = "notification:permission:report"
MAX_RESPONSE_BYTES = 32 * 1024
BOT_BLOCK = "Forbidden: bot was blocked by the user"


@dataclass(frozen=True, repr=False)
class Reply:
    status: int
    body: dict[str, Any]


async def request(client: httpx.AsyncClient, method: str, path: str, **kwargs: Any) -> Reply:
    status = 0
    try:
        async with asyncio.timeout(NETWORK_TIMEOUT):
            async with client.stream(
                method,
                path,
                headers={"Accept-Encoding": "identity", **kwargs.pop("headers", {})},
                **kwargs,
            ) as response:
                status = response.status_code
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    return Reply(status, {})
                data = bytearray()
                async for chunk in response.aiter_raw(chunk_size=4096):
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE_BYTES:
                        return Reply(status, {})
                body = json.loads(data)
                return Reply(status, body if isinstance(body, dict) else {})
    except (httpx.HTTPError, TimeoutError, ValueError, RecursionError):
        return Reply(status, {})


class ServiceTokens:
    def __init__(self, settings: Settings) -> None:
        self.issuer = settings.dispatch_token_issuer
        self.audience = settings.dispatch_token_audience
        self.key_id = settings.dispatch_token_key_id
        secret = settings.dispatch_signing_key_base64
        try:
            if secret is None:
                raise ValueError
            key = serialization.load_pem_private_key(
                base64.b64decode(secret.get_secret_value(), validate=True), password=None
            )
            if not isinstance(key, RSAPrivateKey) or key.key_size < 2048:
                raise ValueError
        except (ValueError, TypeError) as error:
            raise ValueError("invalid_dispatch_signing_key") from error
        self.key = key

    def headers(self, scope: str) -> dict[str, str]:
        now = int(datetime.now(UTC).timestamp())
        token = jwt.encode(
            {
                "iss": self.issuer,
                "aud": self.audience,
                "sub": "notification-service",
                "jti": str(uuid4()),
                "scope": scope,
                "token_use": "service",
                "iat": now,
                "nbf": now,
                "exp": now + 60,
            },
            self.key,
            algorithm="RS256",
            headers={"kid": self.key_id},
        )
        return {"Authorization": f"Bearer {token}"}


class RecipientSnapshot(BaseModel):
    model_config = ConfigDict(strict=True)
    user_id: UUID
    state: Literal["allowed", "unknown", "blocked"]
    telegram_chat_id: int | None = Field(ge=1, le=2**63 - 1)
    revision: int = Field(ge=0, le=2**63 - 1)
    observed_at: AwareDatetime | None
    evidence_kind: str | None


def snapshot(body: dict[str, Any]) -> RecipientSnapshot | None:
    try:
        return RecipientSnapshot.model_validate_json(json.dumps(body))
    except (ValidationError, ValueError, RecursionError):
        return None


def recipient_path(user_id: UUID) -> str:
    return f"/internal/v1/notification-recipients/{user_id}"


class UserClient:
    def __init__(self, client: httpx.AsyncClient, tokens: ServiceTokens) -> None:
        self.client, self.tokens = client, tokens

    async def resolve(self, user_id: UUID) -> Recipient:
        reply = await request(
            self.client, "GET", recipient_path(user_id), headers=self.tokens.headers(READ_SCOPE)
        )
        if reply.status == 404:
            return Recipient("user_missing")
        current = snapshot(reply.body) if reply.status == 200 else None
        if current is None or current.user_id != user_id:
            return Recipient("dependency_unavailable")
        if current.state == "allowed":
            if (
                current.telegram_chat_id is None
                or current.observed_at is None
                or current.evidence_kind not in {"verified_init_data", "write_access_allowed"}
            ):
                return Recipient("dependency_unavailable")
        elif current.telegram_chat_id is not None:
            return Recipient("dependency_unavailable")
        return Recipient(current.state, current.revision, current.telegram_chat_id)

    async def report(self, report: BlockReport) -> ReportResult:
        reply = await request(
            self.client,
            "POST",
            recipient_path(report.user_id) + "/blocked",
            headers=self.tokens.headers(REPORT_SCOPE),
            json={
                "expected_revision": report.revision,
                "telegram_user_id": report.chat_id,
                "notification_id": str(report.notification_id),
                "reason": "bot_forbidden",
            },
        )
        if reply.status == 200:
            current = snapshot(reply.body)
            if current and current.user_id == report.user_id and current.state == "blocked":
                return "reported"
            return "retry"
        if reply.status == 409:
            detail = reply.body.get("detail")
            if isinstance(detail, dict) and detail.get("code") == "REVISION_CONFLICT":
                return "revision_conflict"
            if isinstance(detail, dict) and detail.get("code") == "IDENTITY_MISMATCH":
                return "stale"
            return "rejected"
        if reply.status in {0, 401, 403, 408, 429} or reply.status >= 500:
            return "retry"
        return "rejected"


class BotClient:
    def __init__(self, client: httpx.AsyncClient, token: str) -> None:
        self.client, self.path = client, f"/bot{token}/sendMessage"

    async def send(self, chat_id: int, order_number: str) -> DeliveryResult:
        reply = await request(
            self.client,
            "POST",
            self.path,
            json={
                "chat_id": chat_id,
                "text": f"Заказ {order_number} готов к выдаче.",
                "reply_markup": {
                    "inline_keyboard": [
                        [{"text": "Открыть заказы", "url": "https://maistolovka.me/#orders"}]
                    ]
                },
            },
        )
        if reply.status == 200 and reply.body.get("ok") is True:
            result = reply.body.get("result")
            if isinstance(result, dict):
                chat, message_id = result.get("chat"), result.get("message_id")
                if (
                    isinstance(chat, dict)
                    and chat.get("type") == "private"
                    and type(chat.get("id")) is int
                    and chat["id"] == chat_id
                    and type(message_id) is int
                    and 0 < message_id < 2**63
                ):
                    return DeliveryResult("sent", message_id=message_id)
        if reply.status in {401, 404} or 300 <= reply.status < 400:
            return DeliveryResult("paused")
        error = reply.body.get("ok") is False and reply.body.get("error_code") == reply.status
        if reply.status == 429:
            parameters = reply.body.get("parameters") if error else None
            seconds = parameters.get("retry_after") if isinstance(parameters, dict) else None
            if type(seconds) is int and 0 < seconds <= 2**31 - 1:
                return DeliveryResult("rate_limited", retry_after=seconds)
            # A missing or untrustworthy limit cannot safely be retried automatically.
            return DeliveryResult("paused")
        if reply.status == 403 and error and reply.body.get("description") == BOT_BLOCK:
            return DeliveryResult("blocked")
        if reply.status == 403:
            return DeliveryResult("paused")
        if reply.status == 400 and error:
            return DeliveryResult("bad_request")
        if reply.status in {400, 405, 413, 422}:
            return DeliveryResult("bad_request")
        return DeliveryResult("uncertain")
