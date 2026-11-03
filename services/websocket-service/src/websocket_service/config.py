from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", extra="ignore")

    database_url: SecretStr | None = None
    readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    kafka_bootstrap_servers: str = "localhost:9092"
    jwt_public_key_base64: SecretStr | None = None
    jwt_issuer: str = "mai-food-users"
    jwt_audience: str = "mai-food-api"
    jwt_key_id: str = "local-v1"
    allowed_origins: str = "http://localhost:8081"
    websocket_auth_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    websocket_max_frame_bytes: int = Field(default=12 * 1024, gt=0, le=64 * 1024)
    websocket_queue_size: int = Field(default=128, gt=0, le=4096)

    @property
    def origin_allowlist(self) -> frozenset[str]:
        return frozenset(
            origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()
        )
