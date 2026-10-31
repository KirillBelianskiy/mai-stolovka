# Stage 3 — Transactional Order Service

Scope: ADMIN slots, transactional CLIENT orders, own/staff REST queries, status changes,
cancellation and persisted Outbox events. No relay, notifications, WebSocket delivery, payment
or completed frontend flows. Owner-confirmed policies are in architecture/order-lifecycle.md.

## API

The Order collection is `/api/v1/orders` (bare or trailing slash); there is no repeated `/orders`
segment. Swagger is `/api/v1/orders/docs`. All Order/slot operations require Bearer JWTs.

| Method / path | Behavior |
| --- | --- |
| POST `/api/v1/orders` | CLIENT create; UUID Idempotency-Key header required |
| GET `/api/v1/orders` | CLIENT own history; staff queue/history |
| GET `/api/v1/orders/{id}` | Own order or staff-authorized read |
| PATCH `/api/v1/orders/{id}/status` | Role-checked change with expected_version |
| POST `/api/v1/orders/{id}/cancel` | Policy-checked cancellation with expected_version |
| GET `/api/v1/orders/slots` | Future slots, including full slots, with remaining capacity |
| POST `/api/v1/orders/slots` | ADMIN creates a future, timezone-aware slot |
| PUT / DELETE `/api/v1/orders/slots/{id}` | ADMIN edits/deletes under history/capacity guards |
| POST `/api/v1/menu/item-snapshots` | Public read-only batch of 1–100 unique available dish IDs |

Order lists support repeated status filters, slot_id, limit 1–100 and nonnegative offset. They
return `{items,total,limit,offset}`. Slot lists use the same paging bounds; staff can request
include_past=true. Staff cannot create client orders on behalf of other users.

An order body is:

```json
{
  "slot_id": "<slot UUID>",
  "items": [{"menu_item_id": "<dish UUID>", "quantity": 1}],
  "expected_total_amount": 12000
}
```

Expected total is a confirmation guard; stored prices/totals come only from Menu. A mismatch
returns 409 PRICE_CHANGED with the current amount and no reservation. Obtain confirmation before
a changed submission. Use the same key/body for uncertain retries; use a new key for a new intent.
Unknown fields such as user_id, total_amount and line-item prices are rejected.

HTTP 201 includes immutable line snapshots, authoritative total, slot window, version and order
number. Replays return the original creation body and Idempotency-Replayed=true; GET provides
current state. Client reads of another user's order return 404. Status bodies use
`{status,expected_version}` and cancellation uses `{expected_version}`. A stale mutation conflicts;
repeating an already-successful cancellation cannot free capacity again.

Business errors use `detail:{code,message,...}`; auth/validation errors retain FastAPI's established
format. Common codes: SLOT_FULL, SLOT_CLOSED, PRICE_CHANGED, IDEMPOTENCY_CONFLICT, VERSION_CONFLICT,
CANNOT_CANCEL. Transient failures return 503. Successful replay does not require Menu availability.

## Upgrade the local stack

Preserve existing credentials, keys and volumes. Only the JWT public key is shared with Order.

```sh
uv sync --frozen --project services/order-service
docker compose build menu-service order-service
docker compose run --rm --no-deps --entrypoint /app/.venv/bin/alembic order-service upgrade head
docker compose up -d --wait menu-service order-service proxy
docker compose exec -T proxy nginx -t
docker compose exec -T proxy nginx -s reload
```

Fresh setups also follow the root README for DB credentials/JWT keys and all three migrations.
Migrations never run in application startup. Existing staff and menu data are preserved.

For direct host development, use Order's own DB URL/public key, set
APP_MENU_BASE_URL=http://localhost:8080/api/v1/menu and APP_ROOT_PATH='' for direct Swagger URLs.
Compose defaults to the internal Menu address. HTTP lookup, snapshot freshness and transaction
lock/statement limits are configurable. No Redis or extra gateway is added.

## Verification and next stage

```sh
python3 infra/export-api-contracts.py
python3 infra/run-service-integration.py
python3 -m unittest discover -s tests/smoke -v
```

The integration runner creates isolated User/Menu/Order databases, runs real PostgreSQL tests and
Alembic drift checks, then drops only those databases. Outbox rows are checked against the shared
JSON Schema. Live smoke tests create and remove only their own identities/menu/slot/order data;
application tables are never truncated.

The live client token is minted in User Service for an operator-created test identity. No fake
Telegram login endpoint or production bot token is added. Real Telegram client testing requires
the owner's actual configuration. Both frontend pages remain placeholders in this backend stage.

Jira: SCRUM-8 (creation), SCRUM-9 (lifecycle), SCRUM-10 (integration). Actual results are in
`docs/verification-stage3.md`. The later user authorization publishes the completed Stages 1–3 to `KirillBelianskiy/mai-stolovka`; deployment remains deferred.
Stage 4 adds the Outbox relay and durable consumers after their persistence/delivery decisions.
