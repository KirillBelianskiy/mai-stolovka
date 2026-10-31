# Order Service

Stage 3 implements authenticated orders, slot administration, transactional idempotency,
capacity reservation, immutable menu snapshots, role-based status changes/cancellation and Outbox
persistence. Kafka publication is deferred. See [API and policies](../../docs/stages/stage-3.md).

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
