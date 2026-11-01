# Order Service

Stage 3 implements authenticated orders, slot administration, transactional idempotency,
capacity reservation, immutable menu snapshots, role-based status changes/cancellation and Outbox
persistence. SCRUM-17 adds explicit standalone Outbox publication; the HTTP app never starts it. See [API and policies](../../docs/stages/stage-3.md).

```sh
uv sync --frozen
uv run --frozen alembic upgrade head
uv run --frozen uvicorn order_service.main:create_app --factory --reload --port 8002
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src
uv run --frozen pytest
```

Set APP_DATABASE_URL, APP_JWT_PUBLIC_KEY_BASE64 and APP_MENU_BASE_URL for host development.
Settings are documented in .env.example; files are not loaded automatically. Use orders_owner,
never the bootstrap administrator. Migrations are explicit and never run at startup.
GET /health/live identifies the process; GET /health/ready runs a bounded SELECT 1 and returns
503 without connection details on failure. Readiness does not prove Menu availability.

Each service owns its .venv. PostgreSQL integration tests require an isolated migrated test DB;
from the root, run python3 infra/run-service-integration.py to create, migrate, test and remove
throwaway User/Menu/Order databases. Do not point integration tests at valuable application data.

## Explicit Outbox worker

The HTTP app never starts Kafka publication. The standalone `python -m order_service.outbox`
entrypoint and opt-in Compose `outbox` profile publish existing pending events only after explicit
launch. A pre-existing topic and migrated orders_db are required. Read
[worker launch, failure and rollback instructions](../../docs/stages/stage-4-outbox.md) before running;
starting it will publish the entire pending backlog. Notification/Kitchen consumers remain deferred.
