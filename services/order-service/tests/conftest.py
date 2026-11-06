import asyncio
import base64
import os
import time
from collections.abc import Iterator
from uuid import UUID, uuid4

import asyncpg
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr

from order_service.config import Settings
from order_service.domain.orders import DishSnapshot, OrderError
from order_service.main import create_app


@pytest.fixture(scope="module")
def auth_keys() -> tuple[bytes, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return (
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ),
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        ),
    )


def auth(private: bytes, role: str = "CLIENT", user_id: UUID | None = None) -> dict[str, str]:
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": str(user_id or uuid4()),
            "jti": str(uuid4()),
            "role": role,
            "token_use": "access",
            "iat": now,
            "nbf": now,
            "exp": now + 900,
            "iss": "mai-food-users",
            "aud": "mai-food-api",
        },
        private,
        algorithm="RS256",
        headers={"kid": "local-v1"},
    )
    return {"Authorization": "Bearer " + token}


class FakeMenu:
    def __init__(self) -> None:
        self.dishes: dict[UUID, DishSnapshot] = {}
        self.calls = 0
        self.failed = False

    async def snapshot(self, item_ids: list[UUID]) -> list[DishSnapshot]:
        self.calls += 1
        if self.failed:
            raise OrderError(503, "MENU_UNAVAILABLE", "Menu unavailable")
        if any(item_id not in self.dishes for item_id in item_ids):
            raise OrderError(409, "ITEM_UNAVAILABLE", "Dish unavailable")
        return [self.dishes[item_id] for item_id in item_ids]


@pytest.fixture
def integration_settings(auth_keys: tuple[bytes, bytes]) -> Settings:
    url = os.environ.get("MAI_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Run infra/run-service-integration.py for an isolated PostgreSQL database")

    async def clear() -> None:
        connection = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
        try:
            await connection.execute(
                "TRUNCATE demo_ledger, demo_credit_requests, demo_wallets, "
                "outbox_events, idempotency_records, order_items, "
                "orders, time_slots CASCADE"
            )
        finally:
            await connection.close()

    asyncio.run(clear())
    return Settings(
        database_url=SecretStr(url),
        jwt_public_key_base64=SecretStr(base64.b64encode(auth_keys[1]).decode()),
    )


@pytest.fixture
def integration_client(integration_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(integration_settings)) as client:
        client.app.state.menu = FakeMenu()
        yield client
