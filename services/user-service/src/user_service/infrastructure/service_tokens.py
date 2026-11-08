import base64
from datetime import UTC, datetime
from typing import Literal

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from pydantic import BaseModel, ConfigDict, Field

from user_service.config import Settings

MAX_SERVICE_TOKEN_SECONDS = 300


class NotificationServiceClaims(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sub: Literal["notification-service"]
    jti: str = Field(min_length=1, max_length=128)
    scope: str = Field(min_length=1, max_length=256)
    token_use: Literal["service"]
    iat: int = Field(strict=True)
    nbf: int = Field(strict=True)
    exp: int = Field(strict=True)

    @property
    def scopes(self) -> frozenset[str]:
        return frozenset(self.scope.split())


class NotificationServiceTokenVerifier:
    """Verify the dedicated Notification principal, never end-user access tokens."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.public_key: RSAPublicKey | None = None
        if settings.notification_service_public_key_base64:
            key = serialization.load_pem_public_key(
                base64.b64decode(
                    settings.notification_service_public_key_base64.get_secret_value(),
                    validate=True,
                )
            )
            if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
                raise ValueError("Notification service verification requires RSA-2048 or stronger")
            self.public_key = key

    def verify(self, token: str) -> NotificationServiceClaims:
        if self.public_key is None:
            raise RuntimeError("Notification service authentication is not configured")
        if (
            len(token) > 8192
            or jwt.get_unverified_header(token).get("kid")
            != self.settings.notification_service_key_id
        ):
            raise jwt.InvalidTokenError("Invalid service token")
        payload = jwt.decode(
            token,
            self.public_key,
            algorithms=["RS256"],
            issuer=self.settings.notification_service_issuer,
            audience=self.settings.notification_service_audience,
            options={
                "require": ["exp", "iat", "nbf", "sub", "iss", "aud", "jti", "scope", "token_use"]
            },
        )
        claims = NotificationServiceClaims.model_validate(payload)
        now = int(datetime.now(UTC).timestamp())
        if (
            claims.exp <= claims.iat
            or claims.exp - claims.iat > MAX_SERVICE_TOKEN_SECONDS
            or claims.nbf > now
        ):
            raise jwt.InvalidTokenError("Invalid service token lifetime")
        return claims
