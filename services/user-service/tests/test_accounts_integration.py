import asyncio
import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from user_service.api.accounts import session_token_hash
from user_service.cli import provision_staff, reset_password
from user_service.config import Settings
from user_service.domain.users import Role
from user_service.infrastructure.database import Database
from user_service.infrastructure.models import StaffCredential, User, UserSession

pytestmark = pytest.mark.integration


def init_data(telegram_id: int = 4567890123456, **fields: str) -> str:
    values = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": telegram_id, "first_name": "Иван", "username": "ivan"}),
        **fields,
    }
    text = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    key = hmac.new(b"WebAppData", b"integration-test-only-bot", hashlib.sha256).digest()
    return urlencode({**values, "hash": hmac.new(key, text.encode(), hashlib.sha256).hexdigest()})


def test_telegram_login_profile_and_prohibited_role_edits(integration_client: TestClient) -> None:
    client = integration_client
    result = client.post(
        "/auth/telegram", json={"init_data": init_data()}, headers={"Origin": "https://testserver"}
    )
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store"
    value = result.json()
    assert value["user"]["role"] == "CLIENT"
    headers = {"Authorization": "Bearer " + value["access_token"]}
    assert client.get("/me", headers=headers).json()["id"] == value["user"]["id"]
    public_headers = {**headers, "X-MAI-Public-API": "1"}
    assert client.get("/me", headers=public_headers).json()["id"] == value["user"]["id"]
    assert client.patch("/me", headers=headers, json={"role": "ADMIN"}).status_code == 422
    assert (
        client.patch("/me", headers=public_headers, json={"full_name": "Иван Петров"}).status_code
        == 200
    )
    again = client.post(
        "/auth/telegram", json={"init_data": init_data()}, headers={"Origin": "https://testserver"}
    ).json()
    assert again["user"]["id"] == value["user"]["id"]
    assert again["user"]["full_name"] == "Иван Петров"
    assert "password" not in json.dumps(value)


def test_concurrent_telegram_login_has_one_user(integration_client: TestClient) -> None:
    raw = init_data()
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(
            pool.map(
                lambda _: integration_client.post(
                    "/auth/telegram",
                    json={"init_data": raw},
                    headers={"Origin": "https://testserver"},
                ),
                range(8),
            )
        )
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()["user"]["id"] for response in responses}) == 1


def test_bad_signature_and_stale_data_do_not_create_users(integration_client: TestClient) -> None:
    client = integration_client
    assert (
        client.post(
            "/auth/telegram",
            json={"init_data": init_data() + "&extra=bad"},
            headers={"Origin": "https://testserver"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/telegram",
            json={"init_data": init_data(auth_date="1")},
            headers={"Origin": "https://testserver"},
        ).status_code
        == 401
    )
    assert client.get("/me", headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_staff_provision_login_and_reset(
    integration_client: TestClient, integration_settings: Settings
) -> None:
    password = "integration-only-" + uuid4().hex
    user_id = asyncio.run(
        provision_staff("Chef.Test", "Test Cook", Role.COOK, password, integration_settings)
    )
    client = integration_client
    valid = client.post("/auth/staff", json={"username": "CHEF.TEST", "password": password})
    assert valid.status_code == 200, valid.text
    assert valid.json()["user"]["id"] == user_id
    assert valid.json()["user"]["role"] == "COOK"
    assert valid.json()["user"]["telegram_id"] is None
    known = client.post("/auth/staff", json={"username": "chef.test", "password": "wrong"})
    unknown = client.post("/auth/staff", json={"username": "unknown", "password": "wrong"})
    assert known.status_code == unknown.status_code == 401
    assert known.json() == unknown.json()
    changed = "new-integration-only-" + uuid4().hex
    asyncio.run(reset_password("chef.test", changed, integration_settings))
    assert (
        client.post("/auth/staff", json={"username": "chef.test", "password": password}).status_code
        == 401
    )
    assert (
        client.post("/auth/staff", json={"username": "chef.test", "password": changed}).status_code
        == 200
    )

    async def verify_storage() -> None:
        database = Database(integration_settings.database_url.get_secret_value(), 2)
        try:
            async with database.sessions() as db:
                stored = await db.scalar(select(StaffCredential.password_hash))
                assert stored.startswith("$argon2id$")
                assert password not in stored and changed not in stored
        finally:
            await database.close()

    asyncio.run(verify_storage())


def test_telegram_cannot_log_in_as_staff(
    integration_client: TestClient, integration_settings: Settings
) -> None:
    async def create_staff_identity() -> None:
        database = Database(integration_settings.database_url.get_secret_value(), 2)
        try:
            async with database.sessions() as db, db.begin():
                db.add(User(telegram_id=4567890123456, full_name="Staff", role=Role.ADMIN))
        finally:
            await database.close()

    asyncio.run(create_staff_identity())
    assert (
        integration_client.post(
            "/auth/telegram",
            json={"init_data": init_data()},
            headers={"Origin": "https://testserver"},
        ).status_code
        == 403
    )


def test_public_gateway_rejects_staff_access_tokens(
    integration_client: TestClient, integration_settings: Settings
) -> None:
    client = integration_client
    password = "integration-only-" + uuid4().hex
    for role in (Role.COOK, Role.CASHIER, Role.ADMIN):
        login = f"gateway.{role.value.lower()}"
        user_id = asyncio.run(provision_staff(login, "Staff", role, password, integration_settings))
        auth = client.post("/auth/staff", json={"username": login, "password": password})
        assert auth.status_code == 200
        headers = {"Authorization": f"Bearer {auth.json()['access_token']}"}
        assert client.get("/me", headers=headers).json()["id"] == user_id

        public_headers = {**headers, "X-MAI-Public-API": "1"}
        read = client.get("/me", headers=public_headers)
        write = client.patch("/me", headers=public_headers, json={"full_name": "Changed"})
        for response in (read, write):
            assert response.status_code == 403
            assert response.json() == {"detail": "Customer role required on the public API"}
        assert client.get("/me", headers=headers).json()["full_name"] == "Staff"

    invalid = client.get(
        "/me", headers={"Authorization": "Bearer invalid", "X-MAI-Public-API": "1"}
    )
    assert invalid.status_code == 401
    assert invalid.headers["www-authenticate"] == "Bearer"


def _login(
    client: TestClient, telegram_id: int = 4567890123456, cookie: str | None = None
) -> dict[str, Any]:
    headers = {"Origin": "https://testserver"}
    if cookie is not None:
        headers["Cookie"] = f"mai_session={cookie}"
    response = client.post(
        "/auth/telegram",
        json={"init_data": init_data(telegram_id)},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_session_restore_cookie_storage_restart_logout_and_jwt_expiry_boundary(
    integration_client: TestClient, integration_settings: Settings
) -> None:
    from user_service.main import create_app

    login = _login(integration_client)
    assert login["expires_in"] == 900
    raw_cookie = integration_client.cookies.get("mai_session")
    assert raw_cookie is not None

    async def check_hash_only() -> None:
        database = Database(integration_settings.database_url.get_secret_value(), 2)
        try:
            async with database.sessions() as db:
                stored = await db.scalar(select(UserSession.token_hash))
                assert stored == session_token_hash(raw_cookie)
                assert raw_cookie not in stored
        finally:
            await database.close()

    asyncio.run(check_hash_only())
    restored_app = create_app(integration_settings)
    with TestClient(restored_app, base_url="https://testserver") as restarted:
        restored = restarted.post(
            "/auth/session",
            headers={"Origin": "https://testserver", "Cookie": f"mai_session={raw_cookie}"},
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["user"] == login["user"]
        bearer = {"Authorization": "Bearer " + login["access_token"]}
        assert (
            restarted.post(
                "/auth/logout",
                headers={"Origin": "https://testserver", "Cookie": f"mai_session={raw_cookie}"},
            ).status_code
            == 204
        )
        assert (
            restarted.post("/auth/logout", headers={"Origin": "https://testserver"}).status_code
            == 204
        )
        assert (
            restarted.post(
                "/auth/session",
                headers={"Origin": "https://testserver", "Cookie": f"mai_session={raw_cookie}"},
            ).status_code
            == 401
        )
        assert restarted.get("/me", headers=bearer).status_code == 200


def test_session_cookie_flags_origins_and_missing_invalid_cookie(
    integration_client: TestClient,
) -> None:
    login = integration_client.post(
        "/auth/telegram",
        json={"init_data": init_data()},
        headers={"Origin": "https://testserver"},
    )
    assert login.status_code == 200
    header = login.headers["set-cookie"].lower()
    assert "mai_session=" in header
    assert "secure" in header and "httponly" in header and "samesite=strict" in header
    assert "path=/api/v1/users/auth" in header and "domain=" not in header
    assert login.json().get("session_token") is None
    assert integration_client.post("/auth/session").status_code == 403
    cookie = integration_client.cookies.get("mai_session")
    assert cookie is not None
    for origin in (
        "http://testserver",
        "https://testserver:444",
        "https://testserver.evil.example",
    ):
        headers = {"Origin": origin, "Cookie": f"mai_session={cookie}"}
        assert integration_client.post("/auth/session", headers=headers).status_code == 403
        assert integration_client.post("/auth/logout", headers=headers).status_code == 403
    allowed = {"Origin": "https://testserver", "Cookie": f"mai_session={cookie}"}
    assert integration_client.post("/auth/session", headers=allowed).status_code == 200
    assert (
        integration_client.post(
            "/auth/session",
            headers={"Origin": "https://testserver", "Cookie": "mai_session=invalid"},
        ).status_code
        == 401
    )
    assert (
        integration_client.post(
            "/auth/session", headers={"Origin": "https://testserver"}
        ).status_code
        == 401
    )


def test_session_expiry_and_account_switch_revoke_prior_browser_session(
    integration_client: TestClient, integration_settings: Settings
) -> None:
    first = _login(integration_client, 4567890123456)
    first_cookie = integration_client.cookies.get("mai_session")
    assert first_cookie is not None
    second = _login(integration_client, 4567890123457, first_cookie)
    second_cookie = integration_client.cookies.get("mai_session")
    assert second_cookie is not None and second_cookie != first_cookie
    headers = {"Origin": "https://testserver", "Cookie": f"mai_session={first_cookie}"}
    assert integration_client.post("/auth/session", headers=headers).status_code == 401
    assert second["user"]["id"] != first["user"]["id"]
    restored = integration_client.post(
        "/auth/session", headers={**headers, "Cookie": f"mai_session={second_cookie}"}
    )
    assert restored.status_code == 200
    assert restored.json()["user"]["id"] == second["user"]["id"]

    async def expire_session() -> str:
        database = Database(integration_settings.database_url.get_secret_value(), 2)
        try:
            async with database.sessions() as db:
                session = await db.scalar(
                    select(UserSession).where(
                        UserSession.token_hash == session_token_hash(second_cookie)
                    )
                )
                assert session is not None
                session.idle_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                await db.commit()
        finally:
            await database.close()
        return second_cookie

    expiring = asyncio.run(expire_session())
    assert (
        integration_client.post(
            "/auth/session",
            headers={"Origin": "https://testserver", "Cookie": f"mai_session={expiring}"},
        ).status_code
        == 401
    )

    absolute_login = _login(integration_client, 4567890123458, second_cookie)
    absolute_cookie = integration_client.cookies.get("mai_session")
    assert absolute_cookie is not None and absolute_login["user"]["id"] != second["user"]["id"]

    async def expire_absolute_session() -> None:
        database = Database(integration_settings.database_url.get_secret_value(), 2)
        try:
            async with database.sessions() as db:
                session = await db.scalar(
                    select(UserSession).where(
                        UserSession.token_hash == session_token_hash(absolute_cookie)
                    )
                )
                assert session is not None
                session.idle_expires_at = datetime.now(UTC) + timedelta(days=1)
                session.absolute_expires_at = datetime.now(UTC) - timedelta(seconds=1)
                await db.commit()
        finally:
            await database.close()

    asyncio.run(expire_absolute_session())
    assert (
        integration_client.post(
            "/auth/session",
            headers={"Origin": "https://testserver", "Cookie": f"mai_session={absolute_cookie}"},
        ).status_code
        == 401
    )


def test_parallel_session_restores_are_serialized(
    integration_client: TestClient,
) -> None:
    _login(integration_client)
    token = integration_client.cookies.get("mai_session")
    assert token is not None
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(
            pool.map(
                lambda _: integration_client.post(
                    "/auth/session",
                    headers={"Origin": "https://testserver", "Cookie": f"mai_session={token}"},
                ),
                range(8),
            )
        )
    assert all(response.status_code == 200 for response in responses)
