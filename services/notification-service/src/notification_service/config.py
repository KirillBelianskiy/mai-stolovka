from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", extra="ignore")

    database_url: SecretStr | None = None
    readiness_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    kafka_bootstrap_servers: str = "localhost:9092"
    inbox_topic: str = Field(
        default="orders.events.v1", min_length=1, max_length=249, pattern=r"^[a-zA-Z0-9._-]+$"
    )
    inbox_group: str = Field(
        default="notification-orders-v1", min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._-]+$"
    )
    inbox_operation_timeout_seconds: float = Field(default=15, gt=0, le=30)
    inbox_shutdown_timeout_seconds: float = Field(default=10, gt=0, le=30)
