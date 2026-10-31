import base64
from datetime import UTC, datetime
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from user_service.config import Settings
from user_service.domain.users import Role
from user_service.infrastructure.tokens import TokenVerifier


class TokenIssuer(TokenVerifier):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.private_key: RSAPrivateKey | None = None
        if settings.jwt_private_key_base64:
            key = serialization.load_pem_private_key(
                base64.b64decode(settings.jwt_private_key_base64.get_secret_value(), validate=True),
                password=None,
            )
            if not isinstance(key, RSAPrivateKey) or key.key_size < 2048:
                raise ValueError("JWT signing requires an RSA private key of at least 2048 bits")
            if (
                self.public_key is None
                or key.public_key().public_numbers() != self.public_key.public_numbers()
            ):
                raise ValueError("JWT signing and verification keys do not match")
            self.private_key = key

    def issue(self, user_id: UUID, role: Role) -> str:
        if self.private_key is None:
            raise RuntimeError("Authentication is not configured")
        now = int(datetime.now(UTC).timestamp())
        return jwt.encode(
            {
                "sub": str(user_id),
                "role": role.value,
                "jti": str(uuid4()),
                "iat": now,
                "nbf": now,
                "exp": now + self.settings.access_token_ttl_seconds,
                "iss": self.settings.jwt_issuer,
                "aud": self.settings.jwt_audience,
                "token_use": "access",
            },
            self.private_key,
            algorithm="RS256",
            headers={"kid": self.settings.jwt_key_id},
        )
