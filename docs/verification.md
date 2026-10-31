# Stage 1 verification evidence

Date: 2026-10-30 (Europe/Moscow). Scope: bootstrap only, not business-function acceptance.

## Host checks

Host versions: Python 3.12.8, Node 22.22.2, npm 10.9.7, uv 0.9.5, Docker 29.1.2,
Compose v2.40.3. Container patch releases are explicitly pinned in Dockerfiles/Compose.

| Check | Actual result |
| --- | --- |
| Independent service `uv lock` and `uv sync --frozen` | Passed for all five services |
| Per-service `uv run --frozen ruff check .` | Passed for all five services |
| Per-service `uv run --frozen ruff format --check .` | Passed for all five services |
| Per-service `uv run --frozen mypy src` | Passed for all five services |
| Per-service `uv run --frozen pytest` | User 6, Menu 6, Order 6, Notification 3, WebSocket 3: 24 passed |
| Root `ruff check infra tests` and `ruff format --check infra tests` | Passed |
| `python -m unittest discover -s tests/contracts -v` | 3 passed; schema/examples and invalid envelopes checked |
| `npm ci` | Passed from the root workspace lockfile |
| `npm audit --audit-level=high` | Passed; zero reported vulnerabilities |
| `npm run typecheck` | Passed for both apps, including regeneration after clearing `.next` |
| `NEXT_TELEMETRY_DISABLED=1 npm run build` | Both static exports built successfully |
| `bash -n infra/postgres/01-init.sh` | Passed |
| `docker compose config --quiet` | Passed with generated local credentials |
| `git diff --check` | Passed; product files remain uncommitted as requested |

Service test coverage includes identity/liveness and absence of business routes. Database-backed
health tests cover missing configuration, successful readiness, sanitized failure, and timeout.
Notification/WebSocket health tests cover process readiness only. Tests do not prove future
Kafka/Telegram integration. FastAPI/Starlette emits a TestClient warning about its future HTTP
client transition; all current service tests pass without suppressing the warning.

Restricted host invocations of uv initially failed in macOS SystemConfiguration; the same locked
commands passed when run with the system access uv requires. The deprecated Telegram SDK package
was replaced by its maintained `@tma.js/sdk-react` successor before the clean install/audit.

## Container verification

The initial seven application image builds succeeded. Docker Desktop was initially stopped and
was started for verification. Startup then encountered the existing host PostgreSQL on 5432;
the ignored project `.env` was changed to `POSTGRES_PORT=5433`, preserving the existing server.
The committed defaults remain 5432 and all ports are configurable.

Final command `docker compose --progress plain up --build --wait --wait-timeout 300` passed:
all seven application images built and all ten containers reported healthy. A transient npm
connection reset during the rebuild was resolved by retrying with a BuildKit download cache and
bounded package-fetch retries. No dependency checks were bypassed.

`python3 -m unittest discover -s tests/smoke -v` passed all 5 integration tests in 19.736 seconds:

- Both Russian placeholder pages, all five service identities, and live/ready paths on both origins.
- API prefix forwarding and 404 rejection of unimplemented order/WebSocket paths.
- Three successful own-database connections, six denied cross-database connections, non-superuser
  role flags, and correct database owners.
- Explicit Alembic `upgrade head` for User, Menu, and Order; no business tables created.
- Kafka broker API readiness on the internal listener.

`docker compose exec -T proxy nginx -t` also passed. The verified stack is left running for review
at localhost:8080 and localhost:8081; local host PostgreSQL is on port 5433 for this checkout.

## Skill repositories

- Generated project skill: sibling `mai-food-codex-skill`; member cache `kirill_bel`.
- Codex Skill Forge `validate-skill`: passed before attaching the explicitly requested remote.
- Skill-creator `quick_validate.py`: passed, including after publication.
- Generator tests: 8 passed using `PYTHONDONTWRITEBYTECODE=1` and disabled pytest cache.
- Project skill published to `Bobr2610/mai-food-codex-skill`, commit `52b6384`.
- Generator unchanged and synchronized with `Bobr2610/codex-skill-forge`, commit `9a2815b`.
- Both working trees are clean; private references are ignored and not tracked.
- No redundant Git roots were found. Useful product, generator, and generated-skill repositories
  were preserved. Product Git has no commit or remote.

The generator's initial validator deliberately rejects remotes. The user-requested remote is a
documented exception in project skill v0002; generator source was not modified to bypass it.

## Limits

GitHub Actions is configured but has not been run for the product: no product remote or push was
authorized. There are no business/concurrency/load tests because those implementations are out
of Stage 1 scope. No production deployment, authentication, Telegram send, or WebSocket order
delivery has been verified or claimed.
