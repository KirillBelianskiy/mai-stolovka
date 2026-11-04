# Stage 2 verification

Date: 2026-10-31, Europe/Moscow. Work began on 2026-10-30.
Scope: User/Menu backend, separate staff passwords, contracts, and local integration.

## Test-first evidence

Before endpoint implementation, `tests/test_auth_api.py` failed three assertions because the
profile/authentication routes returned 404; its no-public-registration assertion already passed.
`tests/test_menu_api.py` failed two assertions because public menu and protected-write routes
were missing. These were behavior failures, not missing imports or unavailable infrastructure.

A later failure-path check exposed HTTP 500 for a refused database connection in both services.
The new regression tests expected a sanitized 503. Both tests failed before adding explicit
SQLAlchemy/asyncpg/connection/timeout exception handling, then passed. Programming exceptions
are not converted indiscriminately into dependency failures.

## Executed checks

| Command / area | Result |
| --- | --- |
| Frozen uv resolution/install for User/Menu | Passed; independent lockfiles updated |
| Per-service Ruff, formatting check, strict Mypy | Passed for all five services |
| User `uv run --frozen pytest -q` | 43 passed; 5 PostgreSQL tests explicitly skipped in this invocation |
| Menu `uv run --frozen pytest -q` | 20 passed; 13 PostgreSQL tests explicitly skipped in this invocation |
| Unchanged Order / Notification / WebSocket pytest | 6 / 3 / 3 passed |
| Root Ruff and format checks for infra/tests | Passed |
| Root event schema tests | 3 passed |
| `python3 infra/run-service-integration.py` | User 5, Menu 13 PostgreSQL scenarios passed; no Alembic drift |
| `npm run typecheck` | Both frontends passed |
| `NEXT_TELEMETRY_DISABLED=1 npm run build` | Both static exports passed |
| `docker compose config --quiet` | Passed |
| User/Menu Docker builds and explicit migrations | Passed |
| NGINX configuration test and reload | Passed |

The 18 isolated PostgreSQL cases were actually executed separately; skipped unit-run tests are
not being counted as passing. They cover concurrent login uniqueness, profile persistence and
role-edit rejection, invalid/stale Telegram data, staff provisioning/login/password reset,
Telegram rejection for staff, ADMIN CRUD, denial for CLIENT/COOK/CASHIER, foreign-key conflicts,
availability, pagination, and strict price/URL/input validation. Temporary databases are created
under the relevant service owner and dropped; application databases are never truncated.

Unit checks additionally validate Unicode Telegram identities, large IDs, malformed/duplicate
query fields, optional signature inclusion, freshness, JWT signature/algorithm/kid/issuer/audience/
required claims, Argon2 salts/password limits, unconfigured auth, and unavailable databases.
OpenAPI snapshot tests passed for both services. No business logic was added to other services.

The existing Starlette TestClient/httpx deprecation warning remains visible. A newly encountered
FastAPI constructor deprecation was resolved by configuring the root path in Uvicorn instead.
A transient Docker registry TLS timeout was retried; the successful build did not change pins.

## Final runtime gate

`python3 -m unittest discover -s tests/smoke -v` passed all **7 tests** against the final rebuilt
stack in 23.522 seconds. This included actual staff login, profile access, ADMIN menu writes and
public reads, unauthorized-write rejection, API docs through NGINX, expected schemas, database
isolation, Kafka, and all service health routes. The rate-limit test observed HTTP 429 from a
container source IP, leaving the user's browser IP unthrottled. Test-created staff/menu data was
removed afterward. A follow-up query confirmed zero leftover `stage2_*` test databases.

All ten containers remain healthy. Across the separate suites, 75 service unit/API/contract tests,
18 real PostgreSQL cases, 3 event-schema checks and 7 stack tests passed: **103 distinct tests**.
No skipped PostgreSQL test is counted twice or treated as a pass.

## Jira and repository state

Atlassian access was verified, then the user explicitly selected `dream-team` (`SCRUM`).
SCRUM-5, SCRUM-6, and SCRUM-7 were created with bounded scope/acceptance and assigned to the verified
KirillBelianskiy account. They explicitly record that Jira was connected after implementation
began. Existing starter issues were not changed. The project skill holds task evidence and the
updated Stage 2 authorization in review PR #1; its generic generator is unchanged.
The user subsequently requested autonomous task closure; all three implementation issues were
transitioned to Done after the acceptance checks passed. The separate skill PR remains open for review.

At that Stage 2 closeout, product changes were local and uncommitted, with no product push.
No GitHub Actions run or production deployment was claimed for that closeout.

## Persistent Mini App sessions (SCRUM-40)

Implementation is on branch `SCRUM-40-persistent-user-sessions`, based on `main`. The change adds
User-owned session persistence, cookie-backed restore/logout endpoints, the User OpenAPI snapshot,
and migration/API integration cases for expiry, replay, account switching, parallel restore, and
restart restoration.

| Check | Result |
| --- | --- |
| `python -m compileall` for User source, tests, and migrations | Passed |
| Ruff check and formatting check for User Service | Passed (Ruff 0.8.2 from system Python) |
| `git diff --check` | Passed |
| OpenAPI JSON syntax | Passed |
| User pytest, strict mypy, Alembic/PostgreSQL integration | Not run: this checkout has Python 3.11 only, no `uv`, `asyncpg`, or `pwdlib`; Docker Desktop is stopped |
| Browser regression across engines | Not run: Mini App integration is outside this issue and no local HTTPS app/test runtime is available |

The OpenAPI snapshot was rendered from the app schema using temporary import shims for the missing
`pwdlib` and `asyncpg` packages; this did not execute authentication code. No pytest, database, or
browser compatibility result is inferred from that generation step. Complete the omitted runtime
and browser checks before treating this session flow as verified for integration.

## Practical limits

- No real Telegram/BotFather token was supplied. Telegram verification was tested with generated
  signed vectors and persistent database flows, not a live Telegram client. Without a configured
  real token the live Telegram login endpoint correctly returns 503.
- There is no default/permanent staff account or seeded menu. Provision a real administrator
  interactively using `docs/stages/stage-2.md`; tests clean up their random temporary staff/menu data.
- JWTs expire after 900 seconds by default; password reset does not immediately revoke tokens.
  Production rotation, immediate revocation, account lifecycle/recovery and stronger abuse controls
  remain follow-up decisions documented in `architecture/authentication.md`.
- Both frontend screens remain placeholders. Orders, Kafka delivery, Telegram notifications,
  employee WebSocket updates and production hosting remain outside this stage.
