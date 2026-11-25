import base64
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from pydantic import BaseModel, ConfigDict, Field

from websocket_service.config import Settings


class AccessClaims(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sub: UUID
    jti: UUID
    role: Literal["CLIENT", "COOK", "CASHIER", "ADMIN"]
    token_use: Literal["access"]
    iat: int = Field(strict=True)
    nbf: int = Field(strict=True)
    exp: int = Field(strict=True)


class TokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.public_key: RSAPublicKey | None = None
        if settings.jwt_public_key_base64:
            key = serialization.load_pem_public_key(
                base64.b64decode(settings.jwt_public_key_base64.get_secret_value(), validate=True)
            )
            if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
                raise ValueError(
                    "JWT verification requires an RSA public key of at least 2048 bits"
                )
            self.public_key = key

    def verify(self, token: str) -> AccessClaims:
        if self.public_key is None:
            raise RuntimeError("Authentication is not configured")
        if (
            len(token) > 8192
            or jwt.get_unverified_header(token).get("kid") != self.settings.jwt_key_id
        ):
            raise jwt.InvalidTokenError("Invalid access token")
        payload = jwt.decode(
            token,
            self.public_key,
            algorithms=["RS256"],
            issuer=self.settings.jwt_issuer,
            audience=self.settings.jwt_audience,
            options={
                "require": ["exp", "iat", "nbf", "sub", "iss", "aud", "jti", "role", "token_use"]
            },
        )
        claims = AccessClaims.model_validate(payload)
        if claims.exp <= claims.iat or claims.nbf > int(datetime.now(UTC).timestamp()):
            raise jwt.InvalidTokenError("Invalid access token lifetime")
        return claims
