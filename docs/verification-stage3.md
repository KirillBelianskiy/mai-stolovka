# Stage 3 verification — 2026-10-31

Local execution on macOS, Python 3.12.8, Node 22, Docker Desktop and PostgreSQL 18.
This records actual results, not remote GitHub Actions execution or production acceptance.

## Commands and results

| Command / gate | Actual result |
| --- | --- |
| `uv sync --frozen --project services/<service>` for all five services | Passed; separate frozen environments |
| Each service `.venv/bin/ruff check .` and `ruff format --check .` | Passed |
| Each service `.venv/bin/mypy src` | Passed |
| Each service `.venv/bin/pytest` | User 43, Menu 21, Order 33, Notification 3, WebSocket 3 passed: 103 total |
| `python3 infra/run-service-integration.py` | User 5, Menu 14, Order 18 PostgreSQL cases passed: 37 total |
| Alembic upgrade/check in that runner | All three fresh schemas upgraded; no model/schema drift |
| Root `.venv/bin/ruff check infra tests` and `ruff format --check infra tests` | Passed |
| `.venv/bin/python -m unittest discover -s tests/contracts -v` | 6 passed; formats and event-specific payload/state rules checked |
| `python3 infra/export-api-contracts.py` | User/Menu/Order snapshots exported; service contract tests passed |
| `npm ci` | Passed; 0 audit vulnerabilities reported |
| `npm run typecheck` | Both workspaces passed |
| `npm run build` | Both Next.js static exports passed |
| `docker compose config --quiet` | Passed |
| `docker compose up --build --wait --wait-timeout 300` | Passed; seven application images built and all ten containers healthy |
| `docker compose exec -T proxy nginx -t` and `nginx -s reload` | Passed |
| `python3 -m unittest discover -s tests/smoke -v` | 8 passed against running stack |

Default service pytest runs explicitly skip the 37 database cases when no isolated URL is supplied;
the integration runner separately executed every one of them. Total distinct tests: **154**.
The direct service binaries above use the same frozen uv environments as `uv run --frozen`.
Restricted uv execution hit a host SystemConfiguration issue; frozen sync ran with approved host
access and a temporary cache. Tests ran successfully through the installed service binaries.

## Evidence covered

- Ten concurrent creates against capacity three produce exactly three orders/reservations/events.
- Eight same-key requests replay one original response; changed committed payload conflicts.
- Menu calls occur before the reservation transaction; replay still succeeds when Menu is down.
- Unconfirmed prices, expired snapshots, lock timeout and forced Outbox failure leave no partial writes.
- Immutable prices/names, ownership, role-specific transitions and optimistic versions are enforced.
- Repeated and distinct simultaneous cancellations release capacity correctly; terminal/cutoff rules hold.
- PostgreSQL constraints protect capacity; slots referenced by history cannot be deleted/rescheduled.
- Actual persisted events validate against the shared v1 schema, with one event per changed version.
- Live proxy flow creates/replays an order, changes Menu price, confirms conflict, cancels, then completes
  a new confirmed order. The original response remains replayable after cancellation.
- Both pages, all live/ready routes, database ownership/isolation, Kafka and migration state are checked.

The live client fixture is created by an operator inside User Service and signed by its actual
configured TokenIssuer. Staff login uses the real password API. There is no fake Telegram endpoint
or production test credential. Cleanup removes only fixture-owned data; no application truncation.
The isolated runner drops only its randomly named test databases.

## Test-first and corrections

Before Order endpoints existed, three focused authorization route checks failed with 404 instead
of the expected 401. The missing Menu snapshot route failed with 404 instead of validation 422.
Those checks now pass. Database tests cover later transaction behavior; no invented red run is
claimed for every integration case. Inspection identified stale eager-loaded slot counters during
distinct cancellations; the lock query now refreshes state, and the concurrent regression passes.

## Limits

Starlette emits a TestClient/httpx deprecation warning; tests pass. No real Telegram login was
exercised because no owner bot token is configured. No production load test or security audit is
claimed. Events are persisted only; Kafka relay, notification retries/delivery, WebSocket delivery
and full frontend flows are outside Stage 3. At the time these checks ran, product Git had no commit/remote/push, so GitHub Actions
had not run remotely. Local deployment is development-only.

One full-build attempt hit a temporary ghcr.io TLS handshake timeout; the subsequent identical
command succeeded. No source change or version downgrade was needed.

## Handoff

SCRUM-8/9/10 are Done with verification comments. The separate project-skill v0004 update is
[PR #2](https://github.com/Bobr2610/mai-food-codex-skill/pull/2), stacked on the open Stage 2 review.
Neither PR was merged. The generic skill generator remains unchanged.

Subsequent authorization (2026-10-31): publish the completed product snapshot to
https://github.com/KirillBelianskiy/mai-stolovka.git. Historical local test evidence above is unchanged.

## Follow-up audit

See [SCRUM-11 audit](audit-stage3.md) for source-review findings, post-publication CI evidence,
Git/skill workflow corrections, and checks performed during the audit. Original results above
remain historical evidence of the initial Stage 3 implementation.
