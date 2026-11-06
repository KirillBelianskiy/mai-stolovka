# Demonstration wallet and checkout — MVP #32

Status: implemented for review, not deployed. The owner approved the scheme proposed in
[PR #34](https://github.com/KirillBelianskiy/mai-stolovka/pull/34) on 2026-11-03:
Order Service owns the demo balance, ADMIN credits through Swagger, checkout debits atomically,
and allowed cancellation refunds once. Skill v0012 records this bounded approval; it does not
approve unrelated D2–D10 proposals. UI integration remains #33.

## Ownership and compatibility

`orders_db` owns `demo_wallets`, `demo_credit_requests` and `demo_ledger` under the existing
Order DB role. User UUIDs are external references; the credit operator supplies a verified
customer UUID from User Service. No other service's tables, ORM or credentials are read.
There is no payment provider, real-money deposit, settlement or customer-facing top-up flow.

`APP_DEMO_PAYMENTS_ENABLED` defaults to false. Compose maps `ORDER_DEMO_PAYMENTS_ENABLED`
from the environment; `.env.example` keeps it false. Enable only for a synthetic demonstration.
When enabled, every new order requires demo funds and is stored as `DEMO_PAID`. When disabled,
new orders follow the existing no-payment behavior and are stored as `NOT_REQUIRED`.
This flag is not a way to disable a production payment requirement: there is no real-money mode.

Migration `0002_demo_wallet` assigns existing orders `NOT_REQUIRED`; it never fabricates a debit.
Order reads add `payment_status`: `NOT_REQUIRED`, `DEMO_PAID` or `DEMO_REFUNDED`.
Existing order states/roles/cutoffs and the closed v1 Kafka envelopes remain unchanged.
Original idempotency responses remain original snapshots, including their original payment state;
GET the current order after replay. Older stored responses may omit the new defaulted field.

## HTTP contract

Paths are relative to `/api/v1/orders`; Swagger is `/api/v1/orders/docs`.
All amounts are integer kopecks of synthetic RUB, never floats or browser-authoritative prices.

| Method / path | Authority and behavior |
| --- | --- |
| GET `/wallet` | Any valid API identity reads only its own UUID/balance, `currency=RUB`, `demo=true` and `checkout_payment_enabled`; absent wallet reads zero without creating it |
| POST `/wallet/credits` | ADMIN and enabled demo mode; body `{user_id, amount}`, required UUID `Idempotency-Key`; returns 201 `{id,user_id,amount,balance_after,demo:true}` |
| POST `/` | Existing CLIENT-only checkout/key/body; enabled mode atomically debits the accepted total or returns 409 `INSUFFICIENT_FUNDS` without committed effects |
| POST `/{id}/cancel` | Existing owner/ADMIN rules; refunds a `DEMO_PAID` order and changes its evidence to `DEMO_REFUNDED` in the cancellation transaction |

Credit amounts must be strict positive integers up to 2,147,483,647. A wallet's **lifetime total
credited** is capped at that same amount, even after spending; exceeding it returns 409
`DEMO_CREDIT_LIMIT`. This conservative demo budget guarantees integer headroom for every
outstanding refund, rather than allowing top-ups to make cancellation overflow. There is no
automatic reset or arbitrary balance setter. Zero-priced orders have zero debit/refund entries
and do not need a preceding credit.

Credit keys are globally unique within Order's demo credit API, separate from checkout's
user-scoped keys. Reusing a credit key with the same target/amount returns the original response
with `Idempotency-Replayed: true`, even after later wallet activity. A changed target or amount
returns 409 `IDEMPOTENCY_CONFLICT`. The ledger records the original authenticated ADMIN UUID;
replay by another authorized ADMIN does not change that actor. Never generate another key to
retry an uncertain credit. Keys and durable responses have no automatic expiration.

Non-ADMIN and disabled-credit requests return 403 before DB access. Missing/invalid credentials
follow existing 401/503 behavior. Invalid amounts/extra body fields or malformed/missing keys
return 422. Existing bounded DB/lock failures return 503; roll back before retry with the same
key/body. Wallet/credit responses use `Cache-Control: no-store` and expose no credentials.

## Atomicity, lock order and audit

Checkout retains its short original-response replay lookup and Menu request outside the write
transaction. It claims the checkout key, validates the server total, then locks/upserts the wallet
before locking the slot. It creates the order/items, debits the wallet, appends one DEBIT entry,
stores the response and adds the original creation event in one DB transaction. Any failure,
including Outbox insertion, rolls everything back. Different checkout keys still serialize on
the same wallet; only affordable orders can commit.

Credit claims its global key, locks/upserts one wallet, updates balance/lifetime-credit total,
appends CREDIT and stores its response in one transaction. Cancellation locks an existing order,
checks ownership/role/state/version, locks its wallet and applies refund, then locks/checks the
slot/cutoff and writes status/capacity/event. A later validation failure rolls the refund back.
Repeated cancellation returns current state before another refund. Unique `(order_id,kind)`
entries independently prevent a second DEBIT or REFUND for that order.

Lock graph: create key → wallet → slot → **new** order; credit key → wallet;
cancel **existing** order → wallet → slot. Creation never waits on an existing order,
and no path holds a slot while waiting for a wallet. Status-only changes lock only the order.
No broker/Telegram/Menu call occurs while these locks are held. Existing lock/statement
deadlines bound contention. Real PostgreSQL tests cover mixed credit/checkout/cancel concurrency.

Ledger entries contain UUID, wallet user, kind, nonnegative amount, order/credit reference,
original credit actor and timestamp. PostgreSQL constraints enforce reference shapes and unique
debit/refund/credit references. A DB trigger rejects ordinary UPDATE/DELETE on ledger rows.
There is no ledger mutation API. This is not tamper-proof against a DB owner disabling triggers
or using TRUNCATE; production audit controls are not claimed by a demo feature.

Disabling new demo checkout/credit never disables refunds of already paid orders. Cancelling
legacy `NOT_REQUIRED` orders never mints funds. Completed/READY orders keep the existing
cancellation restrictions. There is no additional payment status event or real-money receipt.

## Swagger walkthrough

1. On an isolated local demonstration, set `ORDER_DEMO_PAYMENTS_ENABLED=true`, build the
   Order image, and explicitly run `docker compose run --rm --no-deps --entrypoint
   /app/.venv/bin/alembic order-service upgrade head` before starting the Order HTTP service.
   Follow the root README for prerequisites. HTTP startup does not run migrations automatically.
   Do not start the optional Outbox profile to demonstrate payment.
2. Use User Service's existing staff login to obtain an ADMIN access token; use real configured
   Telegram login for a customer token. Staff provisioning remains the existing operator-only
   tool. No default admin, fake bot token or unverified customer is added.
3. Open `/api/v1/orders/docs`, select **Authorize**, and paste the ADMIN bearer token. Execute
   POST `/wallet/credits` with a new UUID key and `{"user_id":"<customer UUID>","amount":100000}`
   (1,000 demo rubles). Retain the key/body until its result is certain.
4. Authorize with the customer token; GET `/wallet`, then use existing slot/menu APIs and POST
   `/` with another UUID key and the explicitly accepted server total. Observe `DEMO_PAID` and
   the reduced balance. Retry with the original checkout key/body to demonstrate no second debit.
5. Cancel before slot start while PENDING. Observe `DEMO_REFUNDED` and restored balance; repeat
   cancellation to demonstrate no second refund. Exercise insufficient funds without another debit.

The browser UI in #33 will label synthetic funds in Russian. This implementation supplies the
backend/Swagger contract; it does not claim a finished Mini App, live Telegram demonstration or
complete customer-to-kitchen payment journey.

## Rollback and recovery

Back up orders, keys/responses, wallets, credit requests, ledger and Outbox consistently.
On request ambiguity, replay the same API key/body and then GET current wallet/order state;
do not repair by editing balances or deleting audit entries. Stop new demo intake when
investigating an inconsistency. Keep already paid-order cancellation/refund capability available.

The migration deliberately refuses downgrade instead of deleting payment evidence. A rollback
must retain the payment-capable cancellation code or stop affected writes under a reviewed restore
plan; running old cancellation code against paid orders would omit refunds. Disabling the flag
alone preserves the migrated schema/evidence. Restore/production operational acceptance remains
#28/#29, with no deployment or volume deletion in this task.

Sources checked 2026-11-03: [PostgreSQL 18 row locks](https://www.postgresql.org/docs/18/explicit-locking.html)
and [SQLAlchemy 2.0 PostgreSQL upsert](https://docs.sqlalchemy.org/en/20/orm/queryguide/dml.html#orm-upsert-statements).
They support the serialization/idempotency mechanism; project-specific policy comes from owner
approval and the existing lifecycle. See [verification](../verification-demo-payments.md).
