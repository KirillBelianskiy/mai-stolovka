from fastapi.testclient import TestClient

from notification_service.config import Settings
from notification_service.main import create_app


def test_live_reports_service_identity() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        response = client.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"service": "notification-service", "status": "alive"}


def test_business_routes_are_absent() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        assert client.get("/api/v1/orders").status_code == 404
        assert client.get("/api/v1/ws/kitchen").status_code == 404


def test_process_readiness() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        response = client.get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {"service": "notification-service", "status": "ready"}
