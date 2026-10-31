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
    root_path: str = "/api/v1/menu"
