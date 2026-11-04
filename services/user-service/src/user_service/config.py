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
    jwt_private_key_base64: SecretStr | None = None
    access_token_ttl_seconds: int = Field(default=900, ge=60, le=900)
    telegram_bot_token: SecretStr | None = None
    telegram_init_data_max_age_seconds: int = Field(default=300, ge=30, le=3600)
    session_cookie_allowed_origins: str = "http://localhost:8080,http://localhost:3000"
    notification_service_public_key_base64: SecretStr | None = None
    notification_service_issuer: str = "mai-food-notification"
    notification_service_audience: str = "mai-food-user"
    notification_service_key_id: str = "notification-v1"
    telegram_webhook_secret: SecretStr | None = None
    root_path: str = "/api/v1/users"

    @property
    def allowed_session_origins(self) -> frozenset[str]:
        return frozenset(
            origin.strip()
            for origin in self.session_cookie_allowed_origins.split(",")
            if origin.strip()
        )
