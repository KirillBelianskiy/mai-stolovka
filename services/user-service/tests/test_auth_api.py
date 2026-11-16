from fastapi.testclient import TestClient

from user_service.config import Settings
from user_service.main import create_app


def test_profile_requires_authentication() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        response = client.get("/me")
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"


def test_staff_login_validates_request() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        assert client.post("/auth/staff", json={}).status_code == 422


def test_unconfigured_authentication_fails_closed() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        response = client.post(
            "/auth/telegram",
            json={"init_data": "auth_date=1&hash=invalid"},
            headers={"Origin": "http://localhost:8080"},
        )
        assert response.status_code == 503
        assert "token" not in response.text.lower()


def test_staff_registration_is_not_public() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        assert client.post("/auth/register", json={}).status_code == 404


def test_mini_app_cookie_endpoints_require_allowlisted_origin() -> None:
    with TestClient(create_app(Settings(database_url=None))) as client:
        assert client.post("/auth/session").status_code == 403
        assert (
            client.post(
                "/auth/session", headers={"Origin": "https://untrusted.example"}
            ).status_code
            == 403
        )
        assert (
            client.post("/auth/logout", headers={"Origin": "https://untrusted.example"}).status_code
            == 403
        )


def test_unreachable_database_fails_closed(auth_keys: tuple[bytes, bytes]) -> None:
    import base64

    from pydantic import SecretStr

    private, public = auth_keys
    settings = Settings(
        database_url=SecretStr("postgresql+asyncpg://test:test@127.0.0.1:1/unreachable"),
        jwt_private_key_base64=SecretStr(base64.b64encode(private).decode()),
        jwt_public_key_base64=SecretStr(base64.b64encode(public).decode()),
        readiness_timeout_seconds=0.1,
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        response = client.post(
            "/auth/staff",
            json={
                "username": "unreachable",
                "password": "unit-test-only-password",
            },
        )
        assert response.status_code == 503
        assert response.json() == {"detail": "Database is unavailable"}
