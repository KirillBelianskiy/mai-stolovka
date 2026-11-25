import asyncio
import base64
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from websocket_service.application.hub import KitchenHub
from websocket_service.config import Settings
from websocket_service.main import create_app

ORIGIN = "http://localhost:8081"


@pytest.fixture
def keypair() -> tuple[str, str]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return (
        base64.b64encode(public_pem).decode(),
        base64.b64encode(private_pem).decode(),
    )


def make_token(private_pem_base64: str, role: str = "COOK", expires_in_seconds: int = 300) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(uuid4()),
            "jti": str(uuid4()),
            "role": role,
            "token_use": "access",
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=expires_in_seconds)).timestamp()),
            "iss": "mai-food-users",
            "aud": "mai-food-api",
        },
        base64.b64decode(private_pem_base64),
        algorithm="RS256",
        headers={"kid": "local-v1"},
    )


def app_for(keypair: tuple[str, str]) -> TestClient:
    public_key, _ = keypair
    return TestClient(
        create_app(
            Settings(
                jwt_public_key_base64=public_key,
                allowed_origins=ORIGIN,
            )
        )
    )


def test_websocket_authenticates_staff_and_sends_ready_first(
    keypair: tuple[str, str],
) -> None:
    _, private_key = keypair
    with app_for(keypair) as client:
        with client.websocket_connect(
            "/api/v1/ws/kitchen", headers={"origin": ORIGIN}
        ) as websocket:
            websocket.send_json({"type": "auth", "access_token": make_token(private_key)})
            assert websocket.receive_json() == {"type": "ready"}


def test_websocket_rejects_untrusted_origin(keypair: tuple[str, str]) -> None:
    _, private_key = keypair
    with app_for(keypair) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                "/api/v1/ws/kitchen", headers={"origin": "https://evil.example"}
            ) as websocket:
                websocket.send_json({"type": "auth", "access_token": make_token(private_key)})


def test_websocket_rejects_client_role(keypair: tuple[str, str]) -> None:
    _, private_key = keypair
    with app_for(keypair) as client:
        with client.websocket_connect(
            "/api/v1/ws/kitchen", headers={"origin": ORIGIN}
        ) as websocket:
            websocket.send_json(
                {"type": "auth", "access_token": make_token(private_key, role="CLIENT")}
            )
            with pytest.raises(WebSocketDisconnect) as disconnected:
                websocket.receive_json()
            assert disconnected.value.code == 4403


def test_websocket_rejects_oversized_auth_frame(keypair: tuple[str, str]) -> None:
    with app_for(keypair) as client:
        with client.websocket_connect(
            "/api/v1/ws/kitchen", headers={"origin": ORIGIN}
        ) as websocket:
            websocket.send_text("x" * (12 * 1024 + 1))
            with pytest.raises(WebSocketDisconnect) as disconnected:
                websocket.receive_json()
            assert disconnected.value.code == 1008


def test_websocket_rejects_expired_token(keypair: tuple[str, str]) -> None:
    _, private_key = keypair
    with app_for(keypair) as client:
        with client.websocket_connect(
            "/api/v1/ws/kitchen", headers={"origin": ORIGIN}
        ) as websocket:
            websocket.send_json(
                {
                    "type": "auth",
                    "access_token": make_token(private_key, expires_in_seconds=-1),
                }
            )
            with pytest.raises(WebSocketDisconnect) as disconnected:
                websocket.receive_json()
            assert disconnected.value.code == 4401


def test_websocket_closes_on_token_expiry(keypair: tuple[str, str]) -> None:
    _, private_key = keypair
    with app_for(keypair) as client:
        with client.websocket_connect(
            "/api/v1/ws/kitchen", headers={"origin": ORIGIN}
        ) as websocket:
            websocket.send_json(
                {
                    "type": "auth",
                    "access_token": make_token(private_key, expires_in_seconds=2),
                }
            )
            assert websocket.receive_json() == {"type": "ready"}
            time.sleep(2.1)
            with pytest.raises(WebSocketDisconnect) as disconnected:
                websocket.receive_json()
            assert disconnected.value.code == 4401


def test_websocket_rejects_malformed_auth_frame(keypair: tuple[str, str]) -> None:
    with app_for(keypair) as client:
        with client.websocket_connect(
            "/api/v1/ws/kitchen", headers={"origin": ORIGIN}
        ) as websocket:
            websocket.send_text("not-json")
            with pytest.raises(WebSocketDisconnect) as disconnected:
                websocket.receive_json()
            assert disconnected.value.code == 4401


def test_websocket_rejects_application_frames_after_auth(keypair: tuple[str, str]) -> None:
    _, private_key = keypair
    with app_for(keypair) as client:
        with client.websocket_connect(
            "/api/v1/ws/kitchen", headers={"origin": ORIGIN}
        ) as websocket:
            websocket.send_json({"type": "auth", "access_token": make_token(private_key)})
            assert websocket.receive_json() == {"type": "ready"}
            websocket.send_json({"type": "unexpected"})
            with pytest.raises(WebSocketDisconnect) as disconnected:
                websocket.receive_json()
            assert disconnected.value.code == 1008


def test_websocket_route_is_registered(keypair: tuple[str, str]) -> None:
    with app_for(keypair) as client:
        assert client.get("/api/v1/ws/kitchen").status_code == 404


def test_hub_queues_ready_before_order_hint() -> None:
    hub = KitchenHub(queue_size=2)
    _, client = hub.connect()
    order_id = uuid4()
    asyncio.run(hub.publish_order_hint(order_id, version=3))

    assert client.messages.get_nowait() == {"type": "ready"}
    assert client.messages.get_nowait() == {
        "type": "order.changed",
        "order_id": str(order_id),
        "version": 3,
    }


def test_hub_marks_slow_consumer_for_disconnect() -> None:
    hub = KitchenHub(queue_size=1)
    _, client = hub.connect()
    asyncio.run(hub.publish_order_hint(uuid4(), version=1))

    assert client.overflow.is_set()


def test_slow_consumer_does_not_block_ready_peer() -> None:
    hub = KitchenHub(queue_size=1)
    slow_id, slow = hub.connect()
    fast_id, fast = hub.connect()
    assert fast.messages.get_nowait() == {"type": "ready"}

    asyncio.run(hub.publish_order_hint(uuid4(), version=1))

    assert slow.overflow.is_set()
    assert not fast.overflow.is_set()
    assert fast.messages.get_nowait()["type"] == "order.changed"
    hub.disconnect(slow_id)
    hub.disconnect(fast_id)
    assert hub.clients == {}


def test_hub_shutdown_signals_connections_and_rejects_new_ones() -> None:
    hub = KitchenHub(queue_size=2)
    client_id, client = hub.connect()
    asyncio.run(hub.shutdown())

    assert client.shutdown.is_set()
    with pytest.raises(RuntimeError):
        hub.connect()
    hub.disconnect(client_id)


def test_kafka_enabled_without_assignment_refuses_ready(keypair: tuple[str, str]) -> None:
    public_key, private_key = keypair
    app = create_app(Settings(jwt_public_key_base64=public_key, kitchen_kafka_enabled=True))
    # No broker task is started here, so this verifies the initial admission gate.
    client = TestClient(app)
    assert client.get("/health/ready").status_code == 503
    with client.websocket_connect("/api/v1/ws/kitchen", headers={"origin": ORIGIN}) as websocket:
        websocket.send_json({"type": "auth", "access_token": make_token(private_key)})
        with pytest.raises(WebSocketDisconnect) as disconnected:
            websocket.receive_json()
        assert disconnected.value.code == 1013


def test_websocket_closes_when_stream_is_suspended(keypair: tuple[str, str]) -> None:
    public_key, private_key = keypair
    app = create_app(Settings(jwt_public_key_base64=public_key))
    with TestClient(app) as client:
        with client.websocket_connect(
            "/api/v1/ws/kitchen", headers={"origin": ORIGIN}
        ) as websocket:
            websocket.send_json({"type": "auth", "access_token": make_token(private_key)})
            assert websocket.receive_json() == {"type": "ready"}
            assert client.portal is not None
            client.portal.call(app.state.hub.suspend)
            with pytest.raises(WebSocketDisconnect) as disconnected:
                websocket.receive_json()
            assert disconnected.value.code == 1013
        assert client.get("/health/ready").status_code == 503
