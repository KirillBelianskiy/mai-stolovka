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
    root_path: str = "/api/v1/orders"
    menu_base_url: str = "http://menu-service:8000"
    menu_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    snapshot_max_age_seconds: float = Field(default=5.0, gt=0, le=30)
    transaction_lock_timeout_ms: int = Field(default=1000, ge=10, le=5000)
    transaction_statement_timeout_ms: int = Field(default=3000, ge=100, le=10000)

    outbox_topic: str = Field(default="orders.events.v1", min_length=1, max_length=249)
    outbox_poll_seconds: float = Field(default=1.0, gt=0, le=30)
    outbox_send_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    outbox_shutdown_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    outbox_guard_interval_seconds: float = Field(default=1.0, gt=0, le=5)
    outbox_metrics_interval_seconds: float = Field(default=30.0, gt=0, le=300)
    outbox_backlog_alert_seconds: float = Field(default=60.0, gt=0, le=86400)
    outbox_retry_alert_seconds: float = Field(default=300.0, gt=0, le=86400)
