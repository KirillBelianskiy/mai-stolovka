import base64
from uuid import uuid4

import pytest
from conftest import auth
from fastapi.testclient import TestClient
from pydantic import SecretStr

from order_service.config import Settings
from order_service.main import create_app


def test_wallet_requires_authentication():
    with TestClient(create_app(Settings(database_url=None))) as client:
        assert client.get("/wallet").status_code == 401
        assert client.post("/wallet/credits", json={}).status_code == 401


@pytest.mark.parametrize("role", ["CLIENT", "COOK", "CASHIER"])
def test_credit_denies_non_admin_before_database_access(auth_keys, role):
    settings = Settings(
        database_url=None,
        demo_payments_enabled=True,
        jwt_public_key_base64=SecretStr(base64.b64encode(auth_keys[1]).decode()),
    )
    with TestClient(create_app(settings)) as client:
        assert (
            client.post("/wallet/credits", headers=auth(auth_keys[0], role), json={}).status_code
            == 403
        )


def test_disabled_demo_credit_fails_closed(auth_keys):
    settings = Settings(
        database_url=None,
        jwt_public_key_base64=SecretStr(base64.b64encode(auth_keys[1]).decode()),
    )
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/wallet/credits",
            headers={**auth(auth_keys[0], "ADMIN"), "Idempotency-Key": str(uuid4())},
            json={"user_id": str(uuid4()), "amount": 100},
        )
        assert response.status_code == 403
