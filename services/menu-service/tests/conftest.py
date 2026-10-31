import asyncio
import base64
import os
from collections.abc import Iterator

import asyncpg
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr

from menu_service.config import Settings
from menu_service.main import create_app


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


@pytest.fixture
def integration_settings(auth_keys: tuple[bytes, bytes]) -> Settings:
    url = os.environ.get("MAI_TEST_DATABASE_URL")
    if not url:
        pytest.skip(
            "Run infra/run-service-integration.py to provision an isolated PostgreSQL database"
        )

    async def clear() -> None:
        connection = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://"))
        try:
            await connection.execute("TRUNCATE menu_items, categories CASCADE")
        finally:
            await connection.close()

    asyncio.run(clear())
    private, public = auth_keys
    return Settings(
        database_url=SecretStr(url),
        jwt_public_key_base64=SecretStr(base64.b64encode(public).decode()),
    )


@pytest.fixture
def integration_client(integration_settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(integration_settings)) as client:
        yield client
