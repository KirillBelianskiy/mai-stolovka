# MAI Food

Stage 3 backend foundation for cafeteria preorders: authenticated users, menu administration,
transactional orders, capacity-controlled slots, immutable price snapshots, idempotency,
role-based lifecycle changes, and persisted Outbox events. Kafka/Telegram delivery and complete
frontend flows remain deferred. Both Russian-language screens are placeholders.
See [Stage 3 setup and APIs](docs/stages/stage-3.md) and [Stage 2 authentication](docs/stages/stage-2.md).

## Project layout

```text
apps/{telegram-mini-app,kitchen-app}     Independent static Next.js applications
services/{user,menu}-service             Authentication/profile and menu APIs
services/order-service                  Transactional orders, slots, and persisted Outbox
services/{notification,websocket}-service  Process-only FastAPI shells
packages/contracts                     Language-neutral event schemas and examples
infra/{postgres,nginx}                 Local provisioning and reverse proxy configuration
docs/architecture                      Boundaries, consistency design, open decisions
tests/{contracts,smoke}                 Schema checks and running-stack integration checks
.github/workflows                      Python, frontend, build, and integration gates
skills/                                Existing generator; separate ignored Git repository
```

Start with [architecture overview](docs/architecture/overview.md),
[data ownership](docs/architecture/data-ownership.md),
[order lifecycle](docs/architecture/order-lifecycle.md),
[events](docs/architecture/events.md), and
[open decisions](docs/architecture/open-questions.md).
See [Stage 3 verification](docs/verification-stage3.md) for current checks,
[Stage 2 verification](docs/verification-stage2.md) and
[Stage 1 evidence](docs/verification.md) for the historical bootstrap.

## Prerequisites

- Docker Engine/Desktop with Compose v2, running and available to your terminal.
- Python 3.12 and uv 0.9.5 for host backend development and contract checks.
- Node.js 22 and npm 10+ for host frontend development.

Each service owns its lockfile and `.venv`. The root Python environment contains only contract and
repository checking tools. Do not use the old PyCharm environment for service dependencies.
The root npm workspace has one lockfile. Container image tags are explicit releases, not `latest`.

## Run the local stack

For a pre-populated, isolated demonstration with synthetic Telegram sign-in, six photographed
dishes and staff accounts, follow the [UI demo launch guide](docs/stages/stage-5-ui-completeness.md#reproduce).
It uses ports 8180/8181 and a dedicated Compose project. The lower-level setup below uses 8080/8081.

From the repository root:

```sh
python3 infra/create-local-env.py
python3 infra/create-auth-env.py
docker compose config --quiet
docker compose up --build --wait --wait-timeout 300
docker compose run --rm --no-deps --entrypoint /app/.venv/bin/alembic user-service upgrade head
docker compose run --rm --no-deps --entrypoint /app/.venv/bin/alembic menu-service upgrade head
docker compose run --rm --no-deps --entrypoint /app/.venv/bin/alembic order-service upgrade head
```

The environment helper creates an ignored `.env` with four independent random local passwords and
refuses to overwrite an existing file. Alternatively, copy `.env.example` and fill every empty
password using separate `openssl rand -hex 24` outputs. Use hexadecimal passwords because Compose
embeds service credentials in database URLs. `.env.example` contains no credentials. Never commit
`.env`, render the full resolved Compose configuration into public logs, or reuse local credentials
for deployment.

- Mini App: <http://localhost:8080>
- Kitchen App: <http://localhost:8081>
- Sample liveness: <http://localhost:8080/health/user/live>
- Sample readiness: <http://localhost:8080/health/order/ready>
- PostgreSQL host listener: `localhost:5432`
- Kafka host bootstrap: `localhost:9092`; container bootstrap: `kafka:29092`

Ports can be changed in `.env`. Both app origins expose the API prefixes described in the
architecture overview. The reserved `/api/v1/ws/kitchen` path currently rejects requests; there is
no unauthenticated order stream. PostgreSQL-backed readiness uses a bounded database query;
notification/WebSocket readiness currently proves only that the HTTP process is running.

```sh
docker compose ps
docker compose logs --tail 100 user-service
python3 -m unittest discover -s tests/smoke -v
docker compose down
```

The smoke suite discovers published proxy ports and checks both screens, five services, API
forwarding, reserved WebSocket path, database role isolation, Kafka readiness, current
Alembic schemas, a temporary staff-login/admin-menu flow, and order creation/replay/pricing/cancellation/lifecycle/Outbox persistence. It requires the complete running stack. Fixtures are removed afterward.

PostgreSQL and Kafka data survive `down`. **Destructive reset for disposable local data only:**
`docker compose down --volumes --remove-orphans` permanently removes their volumes. Initialization
scripts run only on the first empty PostgreSQL volume. Editing `.env` after initialization does not
rotate existing database passwords. Rotate them in PostgreSQL explicitly if data must be preserved.

Kafka's plaintext, single-node configuration and the bootstrap DB administrator are local-only.
No Kafka consumers or workers are started by the default stack. Order Service persists events in
PostgreSQL; the explicit opt-in Outbox worker can publish them after topic provisioning. Read
[the worker instructions](docs/stages/stage-4-outbox.md) before launch. The
[development topic tool](docs/stages/stage-4-topic-operations.md) plans explicit provisioning
and checks existing settings; SCRUM-18 consumer integration remains incomplete. Telegram access
will require an HTTPS-accessible deployment and bot interaction permissions in a later stage.

## Backend development and checks

Example for User Service; repeat in each of the five service directories:

```sh
cd services/user-service
uv sync --frozen
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src
uv run --frozen pytest
APP_ROOT_PATH='' uv run --frozen uvicorn user_service.main:create_app --factory --reload --port 8000
```

Other import packages are `menu_service`, `order_service`, `notification_service`, and
`websocket_service`. Use distinct ports for concurrent host processes. Read the per-service
README and `.env.example`; service `.env` files are not loaded automatically.

For database-backed host processes, explicitly export `APP_DATABASE_URL` using
`postgresql+asyncpg://<service-owner>:<local-password>@localhost:5432/<service-db>`.
Supply real values locally; do not paste credentials into issues, source files, or shared logs.
Application settings use the `APP_` environment prefix. Without a database URL a DB-backed shell
still starts, liveness returns 200, and readiness returns 503. Host frontend API integration is
deferred; running through Compose gives same-origin proxy routing.

### Migrations

User, Menu, and Order have initial schema revisions. Run migrations
explicitly before using the APIs; they never execute in application startup:

```sh
docker compose run --rm --no-deps --entrypoint /app/.venv/bin/alembic user-service upgrade head
docker compose run --rm --no-deps --entrypoint /app/.venv/bin/alembic menu-service upgrade head
docker compose run --rm --no-deps --entrypoint /app/.venv/bin/alembic order-service upgrade head
```

For host development, set the matching `APP_DATABASE_URL` and run `uv run --frozen alembic upgrade
head` in the service directory. Later, create revisions with `uv run --frozen alembic revision
--autogenerate -m "Describe the schema change"` and review generated SQL before upgrading.
Do not migrate or connect to another service's database from application code.

## Frontend development and checks

```sh
npm ci
npm run typecheck
npm run build
npm run dev --workspace @mai/telegram-mini-app
# In another terminal:
npm run dev --workspace @mai/kitchen-app
```

Host dev ports are 3000/3001. Builds write static files to each app's ignored `out/` directory.
There is no runtime Next.js server in the containers. Do not add server actions, runtime API
handlers, or default `next/image` optimization without reconsidering static deployment. shadcn/ui
configuration and `cn` helpers are local to each app; a shared UI package is intentionally deferred.
TanStack Query providers are prepared; Zustand and the Mini App SDK are installed but unused.

## Contract checks and CI

```sh
uv sync --frozen
uv run --frozen ruff check infra tests
uv run --frozen python -m unittest discover -s tests/contracts -v
```

GitHub Actions runs independent Python service checks/builds, TypeScript/static builds, contract
validation, and a disposable Compose integration job. CI generates its own temporary credentials
and needs no Telegram token or deployment secret. Workflows do not deploy or publish anything.

The product repository is [KirillBelianskiy/mai-stolovka](https://github.com/KirillBelianskiy/mai-stolovka).
The initial snapshot includes the completed Stages 1–3. Use focused feature branches and review
changes before merging future work. The generator under `skills/` keeps its independent history
and is ignored by the product repository. Do not add it as an
accidental embedded repository or copy its private caches into product commits.

The separate [MAI Food project skill](https://github.com/Bobr2610/mai-food-codex-skill) is generated
from [Codex Skill Forge](https://github.com/Bobr2610/codex-skill-forge). Its local checkout is the
sibling `mai-food-codex-skill` directory, outside product source. The `kirill_bel` member cache
stays private and ignored; the generator source is preserved unchanged.

## Troubleshooting and next work

- If Docker reports that it cannot connect, start Docker Desktop/Engine and verify `docker info`.
- If a port is occupied, change its `.env` value and recreate the affected containers.
- A PostgreSQL authentication failure after changing `.env` usually means the volume still has
  the previous credentials; do not reset valuable data to fix configuration.
- For 503 readiness, inspect DB connectivity and the matching service credentials. Health responses
  deliberately omit connection details.
- Re-run `uv lock` within the owning service only when intentionally changing dependencies; use
  `npm install` at the root for deliberate frontend dependency changes and review the lockfile.

User/Menu/Order backends are implemented. Next agree event delivery/retry and Telegram permission
contracts, implement the Outbox relay and durable Notification processing, then authenticated
WebSocket delivery and frontend integration. The detailed decision register is in
`docs/architecture/open-questions.md`.
