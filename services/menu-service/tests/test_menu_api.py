from fastapi.testclient import TestClient

from menu_service.config import Settings
from menu_service.main import create_app


def test_public_menu_reports_unconfigured_database() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        assert client.get("/categories").status_code == 503
        assert client.get("/items").status_code == 503


def test_menu_writes_require_authentication() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        response = client.post("/categories", json={"name": "Lunch", "sort_order": 0})
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


def test_unreachable_database_returns_sanitized_503() -> None:
    from pydantic import SecretStr

    settings = Settings(
        database_url=SecretStr("postgresql+asyncpg://test:test@127.0.0.1:1/unreachable"),
        readiness_timeout_seconds=0.1,
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.get("/categories")
        assert response.status_code == 503
        assert response.json() == {"detail": "Database is unavailable"}


def test_batch_snapshot_validates_request() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        assert client.post("/item-snapshots", json={"item_ids": []}).status_code == 422
