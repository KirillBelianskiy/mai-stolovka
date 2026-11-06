# Notification Service

HTTP remains a process-only shell. Durable ingestion is an explicitly launched standalone worker
under SCRUM-23/#17; no Telegram dispatcher or public business endpoints are implemented.
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

The HTTP process never starts the Kafka consumer. After explicit local DB provisioning/migration
and topic verification, `python -m notification_service.ingest` or Compose's opt-in `inbox`
profile starts durable ingestion. Normal Compose startup still starts no consumer or bot.
See [the inbox guide](../../docs/stages/stage-4-notification-inbox.md) for setup, recovery and evidence.
