from fastapi.testclient import TestClient

from order_service.config import Settings
from order_service.main import create_app


def test_order_creation_requires_authentication() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        assert client.post("/", json={}).status_code == 401


def test_order_history_requires_authentication() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        assert client.get("/").status_code == 401


def test_slot_creation_requires_authentication() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        assert client.post("/slots", json={}).status_code == 401
