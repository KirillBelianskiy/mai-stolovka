import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import jwt
from fastapi.testclient import TestClient

from user_service.config import Settings


def notification_authorization(
    private: bytes,
    *,
    scope: str = "notification:recipient:read notification:permission:report",
) -> dict[str, str]:
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": "notification-service",
            "jti": str(uuid4()),
            "scope": scope,
            "token_use": "service",
            "iat": now,
            "nbf": now,
            "exp": now + 120,
            "iss": "mai-food-notification",
            "aud": "mai-food-user",
        },
        private,
        algorithm="RS256",
        headers={"kid": "notification-v1"},
    )
    return {"Authorization": f"Bearer {token}"}


def test_recipient_state_webhook_block_idempotency_and_regrant(
    integration_client: TestClient,
    integration_settings: Settings,
    notification_keys: tuple[bytes, bytes],
) -> None:
    client = integration_client
    service_private, _ = notification_keys
    telegram_id = 765432101
    identity = {"id": telegram_id, "first_name": "Иван", "allows_write_to_pm": True}
    raw_fields = {
        "auth_date": str(int(time.time())),
        "user": json.dumps(identity, ensure_ascii=False),
    }
    text = "\n".join(f"{key}={raw_fields[key]}" for key in sorted(raw_fields))
    key = hmac.new(b"WebAppData", b"integration-test-only-bot", hashlib.sha256).digest()
    raw = urlencode(
        {**raw_fields, "hash": hmac.new(key, text.encode(), hashlib.sha256).hexdigest()}
    )
    login = client.post(
        "/auth/telegram",
        json={"init_data": raw},
        headers={"Origin": "https://testserver"},
    )
    assert login.status_code == 200
    user_id = login.json()["user"]["id"]
    headers = notification_authorization(service_private)
    path = f"/internal/v1/notification-recipients/{user_id}"
    user_bearer = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get(path, headers=user_bearer).status_code == 401
    snapshot = client.get(path, headers=headers)
    assert snapshot.status_code == 200
    assert snapshot.json()["state"] == "allowed"
    assert snapshot.json()["telegram_chat_id"] == telegram_id
    assert snapshot.headers["cache-control"] == "no-store"

    report = {
        "expected_revision": snapshot.json()["revision"],
        "telegram_user_id": telegram_id,
        "notification_id": str(uuid4()),
        "reason": "bot_forbidden",
    }
    block_path = f"{path}/blocked"
    with ThreadPoolExecutor(max_workers=4) as pool:
        repeated_reports = list(
            pool.map(
                lambda _: client.post(block_path, json=report, headers=headers),
                range(4),
            )
        )
    assert all(item.status_code == 200 for item in repeated_reports)
    first = repeated_reports[0]
    assert all(item.json() == first.json() for item in repeated_reports)
    assert first.json()["state"] == "blocked"
    replay = client.post(block_path, json=report, headers=headers)
    assert replay.status_code == 200
    assert replay.json() == first.json()
    stale = client.post(
        block_path,
        json={**report, "notification_id": str(uuid4())},
        headers=headers,
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "REVISION_CONFLICT"
    conflict = client.post(
        block_path,
        json={**report, "telegram_user_id": telegram_id + 1},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"

    blocked = client.get(path, headers=headers).json()
    assert blocked["telegram_chat_id"] is None

    update_time = int(time.time()) + 1
    update: dict[str, Any] = {
        "update_id": 99881122,
        "message": {
            "message_id": 7,
            "date": update_time,
            "from": {"id": telegram_id, "is_bot": False, "first_name": "Иван"},
            "chat": {"id": telegram_id, "type": "private"},
            "write_access_allowed": {"from_request": True},
        },
    }
    webhook_headers = {"X-Telegram-Bot-Api-Secret-Token": "integration-only-webhook-secret"}
    webhook = client.post("/internal/v1/telegram/webhook", json=update, headers=webhook_headers)
    assert webhook.status_code == 204
    repeat = client.post("/internal/v1/telegram/webhook", json=update, headers=webhook_headers)
    assert repeat.status_code == 204
    granted = client.get(path, headers=headers).json()
    assert granted["state"] == "allowed"
    assert granted["telegram_chat_id"] == telegram_id

    conflicting_replay = client.post(
        "/internal/v1/telegram/webhook",
        json={**update, "message": {**update["message"], "message_id": 8}},
        headers=webhook_headers,
    )
    assert conflicting_replay.status_code == 409


def test_older_telegram_evidence_cannot_regrant_a_blocked_recipient(
    integration_client: TestClient,
    notification_keys: tuple[bytes, bytes],
) -> None:
    client = integration_client
    service_private, _ = notification_keys
    telegram_id = 765432102
    fields = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": "Иван", "allows_write_to_pm": True}),
    }
    text = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    key = hmac.new(b"WebAppData", b"integration-test-only-bot", hashlib.sha256).digest()
    raw = urlencode({**fields, "hash": hmac.new(key, text.encode(), hashlib.sha256).hexdigest()})
    login = client.post(
        "/auth/telegram",
        json={"init_data": raw},
        headers={"Origin": "https://testserver"},
    )
    assert login.status_code == 200
    user_id = login.json()["user"]["id"]
    headers = notification_authorization(service_private)
    path = f"/internal/v1/notification-recipients/{user_id}"
    snapshot = client.get(path, headers=headers).json()
    report = {
        "expected_revision": snapshot["revision"],
        "telegram_user_id": telegram_id,
        "notification_id": str(uuid4()),
        "reason": "bot_forbidden",
    }
    assert client.post(path + "/blocked", json=report, headers=headers).status_code == 200

    stale_update = {
        "update_id": 99881124,
        "message": {
            "message_id": 9,
            "date": int(time.time()) - 1,
            "from": {"id": telegram_id, "is_bot": False, "first_name": "Иван"},
            "chat": {"id": telegram_id, "type": "private"},
            "write_access_allowed": {"from_request": True},
        },
    }
    accepted = client.post(
        "/internal/v1/telegram/webhook",
        json=stale_update,
        headers={"X-Telegram-Bot-Api-Secret-Token": "integration-only-webhook-secret"},
    )
    assert accepted.status_code == 204
    still_blocked = client.get(path, headers=headers).json()
    assert still_blocked["state"] == "blocked"
    assert still_blocked["telegram_chat_id"] is None


def test_recipient_api_requires_scoped_notification_credentials(
    integration_client: TestClient,
    notification_keys: tuple[bytes, bytes],
) -> None:
    private, _ = notification_keys
    path = "/internal/v1/notification-recipients/00000000-0000-0000-0000-000000000001"
    assert integration_client.get(path).status_code == 401
    no_scope = notification_authorization(private, scope="notification:permission:report")
    assert integration_client.get(path, headers=no_scope).status_code == 403
    read_only = notification_authorization(private, scope="notification:recipient:read")
    assert integration_client.post(path + "/blocked", json={}, headers=read_only).status_code == 403


def test_telegram_webhook_rejects_forged_or_unbound_evidence(
    integration_client: TestClient,
) -> None:
    url = "/internal/v1/telegram/webhook"
    update = {
        "update_id": 99881123,
        "message": {
            "message_id": 1,
            "date": int(time.time()),
            "from": {"id": 7},
            "chat": {"id": 8, "type": "private"},
            "write_access_allowed": {},
        },
    }
    assert integration_client.post(url, json=update).status_code == 403
    forged = integration_client.post(
        url,
        json=update,
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )
    assert forged.status_code == 403
    valid_secret = {"X-Telegram-Bot-Api-Secret-Token": "integration-only-webhook-secret"}
    mismatch = integration_client.post(url, json=update, headers=valid_secret)
    assert mismatch.status_code == 422
