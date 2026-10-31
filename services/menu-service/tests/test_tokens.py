import base64
import time
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr, ValidationError

from menu_service.config import Settings
from menu_service.infrastructure.tokens import TokenVerifier


@pytest.fixture(scope="module")
def keys() -> tuple[bytes, bytes]:
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


def payload() -> dict[str, object]:
    now = int(time.time())
    return {
        "sub": str(uuid4()),
        "jti": str(uuid4()),
        "role": "CLIENT",
        "token_use": "access",
        "iat": now,
        "nbf": now,
        "exp": now + 900,
        "iss": "mai-food-users",
        "aud": "mai-food-api",
    }


def verifier(public: bytes) -> TokenVerifier:
    return TokenVerifier(
        Settings(jwt_public_key_base64=SecretStr(base64.b64encode(public).decode()))
    )


def token(private: bytes, claims: dict[str, object]) -> str:
    return jwt.encode(claims, private, algorithm="RS256", headers={"kid": "local-v1"})


def test_valid_token(keys: tuple[bytes, bytes]) -> None:
    private, public = keys
    assert verifier(public).verify(token(private, payload())).role == "CLIENT"


@pytest.mark.parametrize(
    "field,value",
    [
        ("exp", 1),
        ("iss", "other"),
        ("aud", "other"),
        ("sub", "not-a-uuid"),
        ("role", "SUPERUSER"),
        ("token_use", "refresh"),
        ("iat", "1"),
        ("nbf", 9999999999),
    ],
)
def test_invalid_claims_are_rejected(keys: tuple[bytes, bytes], field: str, value: object) -> None:
    private, public = keys
    claims = payload()
    claims[field] = value
    with pytest.raises((jwt.PyJWTError, ValidationError)):
        verifier(public).verify(token(private, claims))


def test_missing_claim_wrong_key_algorithm_and_key_id_are_rejected(
    keys: tuple[bytes, bytes],
) -> None:
    private, public = keys
    claims = payload()
    del claims["jti"]
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = other_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    invalid = [
        token(private, claims),
        token(other, payload()),
        jwt.encode(
            payload(), "unit-test-only-" * 3, algorithm="HS256", headers={"kid": "local-v1"}
        ),
        jwt.encode(payload(), private, algorithm="RS256", headers={"kid": "unknown"}),
    ]
    for current in invalid:
        with pytest.raises(jwt.PyJWTError):
            verifier(public).verify(current)
