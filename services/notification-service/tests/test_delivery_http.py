import asyncio
import base64
import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from notification_service.config import Settings
from notification_service.dispatch import bot_endpoint
from notification_service.domain.delivery import BlockReport
from notification_service.infrastructure import delivery_http
from notification_service.infrastructure.delivery_http import (
    BOT_BLOCK,
    READ_SCOPE,
    REPORT_SCOPE,
    BotClient,
    ServiceTokens,
    UserClient,
)


class Body(httpx.AsyncByteStream):
    def __init__(self, content):
        self.content = content

    async def __aiter__(self):
        yield self.content


def reply(status, value):
    return httpx.Response(status, stream=Body(json.dumps(value).encode()))


@pytest.mark.parametrize(
    "status, body, outcome, evidence",
    [
        (
            200,
            {"ok": True, "result": {"message_id": 12, "chat": {"id": 1234, "type": "private"}}},
            "sent",
            12,
        ),
        (
            200,
            {"ok": True, "result": {"message_id": 12, "chat": {"id": 4321, "type": "private"}}},
            "uncertain",
            None,
        ),
        (
            429,
            {"ok": False, "error_code": 429, "parameters": {"retry_after": 900}},
            "rate_limited",
            900,
        ),
        (429, {"ok": False, "error_code": 429}, "paused", None),
        (403, {"ok": False, "error_code": 403, "description": BOT_BLOCK}, "blocked", None),
        (403, {"ok": False, "error_code": 403}, "paused", None),
        (401, {}, "paused", None),
        (400, {"ok": False, "error_code": 400}, "bad_request", None),
        (500, {"ok": False, "error_code": 500}, "uncertain", None),
        (302, {}, "paused", None),
    ],
)
def test_bot_transport_preserves_copy_and_classifies_evidence(status, body, outcome, evidence):
    def fake(request):
        assert request.method == "POST" and request.url.path == "/bot0:fake-test-token/sendMessage"
        assert "authorization" not in request.headers
        assert json.loads(request.content) == {
            "chat_id": 1234,
            "text": "Заказ MAI-1 готов к выдаче.",
            "reply_markup": {
                "inline_keyboard": [
                    [{"text": "Открыть заказы", "url": "https://maistolovka.me/#orders"}]
                ]
            },
        }
        return reply(status, body)

    async def check():
        async with httpx.AsyncClient(
            base_url="http://fake.bot", transport=httpx.MockTransport(fake)
        ) as client:
            result = await BotClient(client, "0:fake-test-token").send(1234, "MAI-1")
            assert result.outcome == outcome
            assert (result.message_id or result.retry_after) == evidence

    asyncio.run(check())


def test_lost_ack_timeout_and_oversized_response_are_uncertain(monkeypatch):
    monkeypatch.setattr(delivery_http, "NETWORK_TIMEOUT", 0.02)

    async def fake(request):
        if next(failures) == "timeout":
            await asyncio.sleep(1)
            raise AssertionError("network timeout did not interrupt request")
        return httpx.Response(200, stream=Body(b" " * 32769))

    failures = iter(["timeout", "oversized"])

    async def check():
        async with httpx.AsyncClient(
            base_url="http://fake.bot", transport=httpx.MockTransport(fake)
        ) as client:
            bot = BotClient(client, "0:fake-test-token")
            assert (await bot.send(1234, "MAI-1")).outcome == "uncertain"
            assert (await bot.send(1234, "MAI-1")).outcome == "uncertain"

    asyncio.run(check())


def test_user_transport_uses_exact_routes_contract_and_exclusive_scopes():
    user_id, notification_id = uuid4(), uuid4()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    tokens = ServiceTokens(Settings(dispatch_signing_key_base64=base64.b64encode(pem).decode()))
    seen = set()

    def fake(request):
        bearer = request.headers["Authorization"].removeprefix("Bearer ")
        assert jwt.get_unverified_header(bearer)["kid"] == "notification-v1"
        claims = jwt.decode(
            bearer,
            key.public_key(),
            algorithms=["RS256"],
            audience="mai-food-user",
            issuer="mai-food-notification",
        )
        assert claims["sub"] == "notification-service" and claims["token_use"] == "service"
        assert claims["exp"] - claims["iat"] == 60 and claims["iat"] == claims["nbf"]
        assert claims["jti"] not in seen
        seen.add(claims["jti"])
        path = f"/internal/v1/notification-recipients/{user_id}"
        if request.method == "POST":
            assert request.url.path == path + "/blocked" and claims["scope"] == REPORT_SCOPE
            assert json.loads(request.content) == {
                "expected_revision": 7,
                "telegram_user_id": 1234,
                "notification_id": str(notification_id),
                "reason": "bot_forbidden",
            }
            return reply(409, {"detail": {"code": "REVISION_CONFLICT", "revision": 8}})
        assert request.url.path == path and claims["scope"] == READ_SCOPE
        return reply(
            200,
            {
                "user_id": str(user_id),
                "state": "allowed",
                "telegram_chat_id": 1234,
                "revision": 7,
                "observed_at": datetime.now(UTC).isoformat(),
                "evidence_kind": "write_access_allowed",
            },
        )

    async def check():
        async with httpx.AsyncClient(
            base_url="http://fake.user", transport=httpx.MockTransport(fake)
        ) as client:
            user = UserClient(client, tokens)
            recipient = await user.resolve(user_id)
            assert (recipient.state, recipient.chat_id, recipient.revision) == ("allowed", 1234, 7)
            report = BlockReport(user_id, notification_id, 7, 1234, "pending", 0)
            assert await user.report(report) == "revision_conflict"

    asyncio.run(check())


def test_bot_defaults_to_disabled_and_fake_mode_uses_only_synthetic_token(monkeypatch):
    monkeypatch.delenv("APP_DISPATCH_BOT_MODE", raising=False)
    assert Settings().dispatch_bot_mode == "disabled"
    with pytest.raises(ValueError):
        bot_endpoint(
            Settings(dispatch_bot_mode="fake", dispatch_fake_bot_url="https://api.telegram.org")
        )
    assert bot_endpoint(
        Settings(dispatch_bot_mode="fake", dispatch_fake_bot_url="http://fake.bot")
    ) == ("http://fake.bot/", "0:fake-test-token")
