# User Service

Stage 2 Telegram client/staff authentication and own-profile API.
See the root README and architecture documents for responsibilities and local infrastructure.

## Notification recipient permission contract

User Service owns the verified Telegram identity-to-recipient mapping and permission state.
Only a fresh, HMAC-verified raw Telegram `initData` carrying `allows_write_to_pm: true`, or a
Telegram `WriteAccessAllowed` update accepted through the single secret-authenticated webhook,
can grant permission. Missing evidence never grants or revokes permission. An authenticated
Notification service can resolve one recipient or report a definitive recipient block; it cannot
read profile data or access `users_db` directly.

Internal paths (after the existing `/api/v1/users` proxy prefix):

- `GET /internal/v1/notification-recipients/{user_id}` requires the
  `notification:recipient:read` scope.
- `POST /internal/v1/notification-recipients/{user_id}/blocked` requires the separate
  `notification:permission:report` scope and uses `notification_id` plus `reason` for idempotency.
- `POST /internal/v1/telegram/webhook` is the single public Telegram intake and requires the configured
  `X-Telegram-Bot-Api-Secret-Token` header and durably deduplicates `update_id` before returning.

Notification service JWTs must be RS256, expire within five minutes, and contain `iss`, `aud`,
`sub=notification-service`, unique `jti`, `token_use=service`, and space-delimited scopes. Keep the
Notification private signing key only in Notification; configure its separate public key and
matching issuer/audience/key id in User Service. Never reuse end-user JWT keys or log credentials,
raw webhook bodies, Telegram IDs, or response bodies. Provision the webhook secret out of band;
production key management, webhook registration, token rotation, freshness limits and retention
remain deployment-owner decisions.

From this directory:

```sh
uv sync --frozen
APP_ROOT_PATH='' uv run --frozen uvicorn user_service.main:create_app --factory --reload --port 8000
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src
uv run --frozen pytest
```

The environment lives in this service's `.venv`; it is not the root PyCharm environment.
Set environment variables explicitly; `.env.example` is documentation and is not loaded automatically.
Choose another port when running several service processes on the host.

Mini App auth uses `APP_SESSION_COOKIE_ALLOWED_ORIGINS` as a comma-separated exact-origin allowlist.
Set the actual origin(s) used by the Mini App. The `mai_session` cookie is Secure, HttpOnly, host-only, SameSite=Strict,
and scoped to `/api/v1/users/auth`. Use local HTTPS for browser engines that reject Secure cookies
on HTTP localhost.

- `GET /health/live`: process availability and service identity.
- `GET /health/ready`: bounded PostgreSQL query; 503 when unconfigured or unavailable.

For host development, export `APP_DATABASE_URL` with the `postgresql+asyncpg` scheme, localhost PostgreSQL port, matching database name, and this service owner credentials. Run `uv run --frozen alembic upgrade head` explicitly. The initial Stage 2 schema revision must be applied before using business endpoints. Never use bootstrap-admin credentials in the application.

See `../../docs/stages/stage-2.md` and `../../docs/architecture/authentication.md` for
API contracts, JWT configuration, provisioning and verification. PostgreSQL integration tests
are explicitly skipped in a plain pytest run; run `python3 infra/run-service-integration.py`
from the product root to execute them in temporary databases.
