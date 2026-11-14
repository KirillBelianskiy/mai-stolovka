# Notification Service

HTTP serves process health. Durable ingestion (SCRUM-23/#17) and Telegram READY delivery
(SCRUM-24/#18) run as separate standalone workers.
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

## READY delivery (#18)

Apply the Notification database migration `0002_ready_dispatch` after `0001_inbox`.
Existing obligations are picked up from the inbox with their original READY timestamp.

```sh
uv run --frozen alembic upgrade 0002_ready_dispatch
uv run --frozen python -m notification_service.dispatch --check
uv run --frozen python -m notification_service.dispatch
```

For the service image, use `/app/.venv/bin/alembic` and
`/app/.venv/bin/python -m notification_service.dispatch`. Run one dispatcher against the
Notification database. A second process exits if the database advisory lock is held, and the
persisted claim prevents overlapping attempts during takeover. Give the process at least 45
seconds to shut down gracefully so the current bounded work can record its outcome.

`--check` exits zero when dispatch is enabled, configuration validates, and the migrated
Notification database is reachable. It does not contact dependencies or check the worker's
progress. A dispatch-only container should replace the HTTP image health check with
`/app/.venv/bin/python -m notification_service.dispatch --check`. Monitor process exits,
`dispatch_bot.paused` and `dispatch_bot.cooldown_until`, and the age of due
`ready_dispatches` and pending block reports. The HTTP `/health/ready` stays process-only.

Set `APP_DATABASE_URL`, `APP_DISPATCH_USER_URL`, and
`APP_DISPATCH_SIGNING_KEY_BASE64` in the dispatch process. The User URL is the private service
origin. User must have the matching `APP_NOTIFICATION_SERVICE_PUBLIC_KEY_BASE64`, and both
sides must agree on token issuer, audience, and key ID. Notification issues a fresh 60-second
RS256 token per call with exactly one scope. The User lookup is repeated before every send.
Unknown or unavailable snapshots are checked every 30 seconds up to the original expiry.

Use `APP_DISPATCH_BOT_MODE=fake` with `APP_DISPATCH_FAKE_BOT_URL` for synthetic validation.
Fake mode supplies a fixed dummy token. Use an isolated, disposable database and User configuration
for fake runs. Once delivery evidence exists, keep the Notification database bound to the same
bot and environment. `disabled` is the default.

For a separately authorized controlled real test, use `APP_DISPATCH_BOT_MODE=telegram` and
`APP_DISPATCH_BOT_TOKEN` for the same bot configured in User. The destination is fixed to Telegram's
HTTPS API. First verify the private recipient routes, the single secret-authenticated User webhook
through the approved public mapping, the permitted test account's grant, and authenticated entry
through `https://maistolovka.me/#orders` under #25/#27. Use an isolated approved test account and
synthetic READY order. Configuration and health checks do not establish live delivery.

A pending attempt is durable before sending. A lost result or expired in-flight claim records an
uncertain attempt and possible duplication. At most eight attempts start in the 24-hour window.
Rate limits persist as a shared cooldown, even when the triggering order expires. A definitive
private-chat block stops the obligation and stages an idempotent User report. Delivery to the same user stays blocked while User still returns
that revision. The report uses the original permission revision. A revision conflict causes a fresh lookup and retires the stale report.
The pending report's destination is access-restricted database data and is cleared once it is no
longer needed. Logs omit request URLs, bodies and recipient identifiers.

A bot-wide pause persists across restarts. After stopping dispatch and fixing the configuration,
an authorized operator can clear it in the Notification database with
`UPDATE dispatch_bot SET paused = false WHERE id = 1;`. Preserve any existing cooldown.
Inspect terminal failures in `ready_dispatches` and attempt evidence in `delivery_attempts`.
Rolling back the worker means stopping it and leaving dispatch disabled. Preserve its tables to
avoid resetting delivery history.

Transport reference for [sendMessage](https://core.telegram.org/bots/api#sendmessage) and
[retry_after](https://core.telegram.org/bots/api#responseparameters), checked 2026-11-14.
