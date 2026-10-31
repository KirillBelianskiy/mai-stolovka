import asyncio
import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from user_service.cli import provision_staff, reset_password
from user_service.config import Settings
from user_service.domain.users import Role
from user_service.infrastructure.database import Database
from user_service.infrastructure.models import StaffCredential, User

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
    result = client.post("/auth/telegram", json={"init_data": init_data()})
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store"
    value = result.json()
    assert value["user"]["role"] == "CLIENT"
    headers = {"Authorization": "Bearer " + value["access_token"]}
    assert client.get("/me", headers=headers).json()["id"] == value["user"]["id"]
    assert client.patch("/me", headers=headers, json={"role": "ADMIN"}).status_code == 422
    assert (
        client.patch("/me", headers=headers, json={"full_name": "Иван Петров"}).status_code == 200
    )
    again = client.post("/auth/telegram", json={"init_data": init_data()}).json()
    assert again["user"]["id"] == value["user"]["id"]
    assert again["user"]["full_name"] == "Иван Петров"
    assert "password" not in json.dumps(value)


def test_concurrent_telegram_login_has_one_user(integration_client: TestClient) -> None:
    raw = init_data()
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(
            pool.map(
                lambda _: integration_client.post("/auth/telegram", json={"init_data": raw}),
                range(8),
            )
        )
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()["user"]["id"] for response in responses}) == 1


def test_bad_signature_and_stale_data_do_not_create_users(integration_client: TestClient) -> None:
    client = integration_client
    assert (
        client.post("/auth/telegram", json={"init_data": init_data() + "&extra=bad"}).status_code
        == 401
    )
    assert (
        client.post("/auth/telegram", json={"init_data": init_data(auth_date="1")}).status_code
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
        integration_client.post("/auth/telegram", json={"init_data": init_data()}).status_code
        == 403
    )
