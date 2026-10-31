# Stage 2 — User and Menu backend

Scope explicitly confirmed by the owner: User/Menu APIs and migrations; staff password accounts
with secure operator provisioning. Orders, event delivery, full frontend flows, and deployment
remain excluded. Stage 1 verification evidence is historical, not the current API inventory.

## API contracts

OpenAPI snapshots are in `packages/contracts/openapi/`. CI tests compare each service's schema
against its snapshot. After an intentional API change, run `python3 infra/export-api-contracts.py`
and review the diff. API root prefixes are owned by NGINX and removed before routing upstream.
Swagger is available at `/api/v1/users/docs` and `/api/v1/menu/docs` through either local origin.

| Method and external path | Behavior |
| --- | --- |
| POST `/api/v1/users/auth/telegram` | Verify `{"init_data":"original query string"}`; persist CLIENT; return token and profile |
| POST `/api/v1/users/auth/staff` | Authenticate `{"username":"login","password":"…"}`; return token and profile |
| GET `/api/v1/users/me` | Bearer-authenticated own profile |
| PATCH `/api/v1/users/me` | Update only `full_name`; unknown fields such as role are rejected |
| GET `/api/v1/menu/categories` | Public list ordered by sort_order, UUID |
| GET `/api/v1/menu/items` | Public available dishes; optional category_id, limit 1–100, offset >= 0 |
| GET `/api/v1/menu/items/{id}` | Available dish or 404 |
| GET `/api/v1/menu/admin/items` | ADMIN list including unavailable dishes, with pagination |
| POST `/api/v1/menu/categories` | ADMIN create; returns 201 |
| PUT / DELETE `/api/v1/menu/categories/{id}` | ADMIN replace / delete; linked dishes prevent deletion with 409 |
| POST `/api/v1/menu/items` | ADMIN create; returns 201 |
| PUT / DELETE `/api/v1/menu/items/{id}` | ADMIN replace / delete |

Login responses contain `access_token`, `token_type=bearer`, `expires_in`, and `user`. Profiles
contain UUID, nullable Telegram ID/username, full name, role, and timezone-aware creation time.
Passwords, password hashes, and signing material are never response fields. Token/profile
responses use `Cache-Control: no-store`.

Item lists return `{items,total,limit,offset}`. Prices are strict integer kopecks between 0 and
2147483647; zero is a documented reversible default, not a confirmed free-meal business rule.
Item names/categories cannot be blank; images accept HTTP(S) URLs only. Availability is a strict
boolean. PUT replaces the full resource representation; it is not a partial update. Unknown
fields are rejected. Dish ordering is by name then UUID. Count/list consistency under concurrent
admin edits is ordinary read-committed behavior, not a snapshot guarantee.

401 means absent/invalid authentication, 403 means an insufficient role, 404 means no visible
resource, 409 means a foreign-key/current-data conflict, 422 means invalid input, and 503 means
an unavailable database or unconfigured authentication. NGINX may return 429 for staff-login
rate limiting. Staff auth policy and token limitations are in `architecture/authentication.md`.

## Setup from an existing Stage 1 checkout

Keep the existing `.env`; do not regenerate its database credentials or delete volumes.

```sh
python3 infra/create-auth-env.py
docker compose build user-service menu-service
docker compose run --rm --no-deps --entrypoint /app/.venv/bin/alembic user-service upgrade head
docker compose run --rm --no-deps --entrypoint /app/.venv/bin/alembic menu-service upgrade head
docker compose up -d --wait user-service menu-service proxy
docker compose exec -T proxy nginx -t
docker compose exec -T proxy nginx -s reload
```

The auth helper runs once and refuses key replacement. Add a real `TELEGRAM_BOT_TOKEN` to ignored
`.env` locally to enable Telegram authentication, then recreate User Service. Do not send the token
through chat. No bot token is needed for staff login or menu administration.

Provision the first administrator interactively; the password is not an argument:

```sh
docker compose run --rm --no-deps --entrypoint /app/.venv/bin/python user-service \
  -m user_service.cli provision-staff --username cafeteria.admin --full-name "Cafeteria Admin" --role ADMIN
```

Choose COOK or CASHIER for subsequent staff accounts. Reset using the same command prefix with
`-m user_service.cli reset-password --username cafeteria.admin`; old access tokens retain their
bounded lifetime. There is no default operator account, password, or seeded menu. Use the staff
login API and its Bearer token in Swagger to manage the menu. Protect real credentials with TLS.

## Verification

Run service Ruff/Mypy/pytest commands as documented in their READMEs. Ordinary pytest runs skip
PostgreSQL-only tests explicitly; the integration runner provisions isolated temporary databases,
runs migrations/tests/drift checks, and drops only those generated databases afterward:

```sh
uv sync --frozen --project services/user-service
uv sync --frozen --project services/menu-service
python3 infra/run-service-integration.py
python3 -m unittest discover -s tests/smoke -v
```

The stack smoke suite applies the current forward migrations to local app databases and checks
their schema. Its end-to-end staff/admin flow uses a random, temporary account and menu records,
then removes only those records. It never truncates existing local application data. Temporary
database tests truncate only their own newly created test database, never users_db or menu_db.

CI includes both isolated database suites and the real proxy/User/Menu flow. Actual executed
results and limitations belong in `docs/verification-stage2.md`.

## Jira

The owner confirmed the existing `dream-team` project (`SCRUM`). Tracking was connected after
implementation began, so issue descriptions record that timing rather than claim prior Jira use.

- SCRUM-5: User authentication and staff accounts.
- SCRUM-6: Menu browsing and administrator API.
- SCRUM-7: Contracts, auth setup, and integration gates.

Existing starter issues were preserved. No product Git remote, commit, push, or release is
authorized by this stage. The next stage is the transactional Order Service after agreeing its
remaining slot, cancellation, pricing, and idempotency policies.
