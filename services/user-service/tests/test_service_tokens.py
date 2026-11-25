import base64
import time
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

from user_service.config import Settings
from user_service.infrastructure.service_tokens import NotificationServiceTokenVerifier


@pytest.fixture(scope="module")
def service_keys() -> tuple[bytes, bytes]:
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


def service_token(
    private: bytes, *, scope: str = "notification:recipient:read", lifetime: int = 120
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": "notification-service",
            "jti": str(uuid4()),
            "scope": scope,
            "token_use": "service",
            "iat": now,
            "nbf": now,
            "exp": now + lifetime,
            "iss": "mai-food-notification",
            "aud": "mai-food-user",
        },
        private,
        algorithm="RS256",
        headers={"kid": "notification-v1"},
    )


def verifier(public: bytes) -> NotificationServiceTokenVerifier:
    settings = Settings(
        notification_service_public_key_base64=SecretStr(base64.b64encode(public).decode())
    )
    return NotificationServiceTokenVerifier(settings)


def test_scoped_short_lived_notification_token_is_accepted(
    service_keys: tuple[bytes, bytes],
) -> None:
    private, public = service_keys
    claims = verifier(public).verify(service_token(private))
    assert claims.sub == "notification-service"
    assert claims.scopes == frozenset({"notification:recipient:read"})


@pytest.mark.parametrize(
    "changes",
    [
        {"iss": "another-service"},
        {"aud": "another-service"},
        {"sub": "user"},
        {"token_use": "access"},
        {"exp": 1},
    ],
)
def test_wrong_principal_claims_and_expiry_are_rejected(
    service_keys: tuple[bytes, bytes], changes: dict[str, object]
) -> None:
    private, public = service_keys
    now = int(time.time())
    claims: dict[str, object] = {
        "sub": "notification-service",
        "jti": str(uuid4()),
        "scope": "notification:recipient:read",
        "token_use": "service",
        "iat": now,
        "nbf": now,
        "exp": now + 120,
        "iss": "mai-food-notification",
        "aud": "mai-food-user",
    }
    claims.update(changes)
    invalid = jwt.encode(claims, private, algorithm="RS256", headers={"kid": "notification-v1"})
    with pytest.raises((jwt.PyJWTError, ValueError)):
        verifier(public).verify(invalid)


def test_service_tokens_reject_wrong_key_and_long_lifetime(
    service_keys: tuple[bytes, bytes],
) -> None:
    private, public = service_keys
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other_private = other.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with pytest.raises(jwt.PyJWTError):
        verifier(public).verify(service_token(other_private))
    with pytest.raises(jwt.PyJWTError):
        verifier(public).verify(service_token(private, lifetime=301))
