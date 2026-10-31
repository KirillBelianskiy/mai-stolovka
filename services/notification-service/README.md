# Notification Service

Stage 1 shell only. Owns no implemented business endpoints.
See the root README and architecture documents for responsibilities and local infrastructure.

From this directory:

```sh
uv sync --frozen
uv run --frozen uvicorn notification_service.main:create_app --factory --reload --port 8000
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src
uv run --frozen pytest
```

The environment lives in this service's `.venv`; it is not the root PyCharm environment.
Set environment variables explicitly; `.env.example` is documentation and is not loaded automatically.
Choose another port when running several service processes on the host.

- `GET /health/live`: process availability and service identity.
- `GET /health/ready`: process only; Kafka/Telegram integrations are not started.

Kafka configuration is reserved for later integration. No consumer, bot, or WebSocket handler is running.
