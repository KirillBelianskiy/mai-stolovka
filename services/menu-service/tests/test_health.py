from fastapi.testclient import TestClient

from menu_service.config import Settings
from menu_service.main import create_app


def test_live_reports_service_identity() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"service": "menu-service", "status": "alive"}


def test_business_routes_are_absent() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        assert client.get("/api/v1/orders").status_code == 404
        assert client.get("/api/v1/ws/kitchen").status_code == 404


def test_missing_database_is_not_ready() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        assert client.get("/health/ready").status_code == 503


def test_database_success_reports_ready() -> None:
    from unittest.mock import AsyncMock

    app = create_app(Settings(database_url=None))
    with TestClient(app) as client:
        app.state.database = AsyncMock()
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {"service": "menu-service", "status": "ready"}
        app.state.database.check_ready.assert_awaited_once()


def test_database_failure_does_not_expose_credentials() -> None:
    from unittest.mock import AsyncMock

    app = create_app(Settings(database_url=None))
    with TestClient(app) as client:
        app.state.database = AsyncMock()
        app.state.database.check_ready.side_effect = RuntimeError("secret-connection-details")
        response = client.get("/health/ready")
        assert response.status_code == 503
        assert response.json() == {"service": "menu-service", "status": "not_ready"}
        assert "secret" not in response.text


def test_database_readiness_is_bounded() -> None:
    import asyncio
    from unittest.mock import AsyncMock

    async def slow_check() -> None:
        await asyncio.sleep(10)

    app = create_app(Settings(database_url=None, readiness_timeout_seconds=0.01))
    with TestClient(app) as client:
        app.state.database = AsyncMock()
        app.state.database.check_ready.side_effect = slow_check
        assert client.get("/health/ready").status_code == 503
