# Order lifecycle and consistency — Stage 3

Status: implemented and tested against PostgreSQL. The owner confirmed these policies on
2026-10-31. Events are persisted in the Outbox; no Kafka relay is running yet.

| Action | Accepted rule |
| --- | --- |
| Create an order | CLIENT; one capacity unit per order, regardless of item count |
| Booking cutoff | Slot start, using server time |
| PENDING → PREPARING | COOK or ADMIN |
| PREPARING → READY | COOK or ADMIN |
| READY → COMPLETED | CASHIER or ADMIN |
| Cancel PENDING | Owning CLIENT or ADMIN, before slot start |
| Cancel PREPARING | ADMIN only, before slot start |
| View orders | CLIENT sees only own orders; staff can read queue/history |
| Manage slots | ADMIN; no schedule edits once any order references a slot |

COMPLETED/CANCELLED are terminal. Completed orders retain historical slot allocation;
cancellation releases capacity once. There is no order deletion API. Referenced slots, including
cancelled history, cannot be deleted; capacity cannot fall below reservations. All dates require
offsets and are stored as timezone-aware values. No recurring calendar or overlapping-slot
exclusion is invented; capacity belongs to the selected slot.

## Creation transaction

1. Validate CLIENT, cart, expected total and UUID Idempotency-Key. Normalize cart ordering by
   unique dish IDs; quantities must be strict positive integers. Reject client prices/user IDs.
2. Check `(user_id,key)` in a short read session. A committed matching request replays its exact
   original HTTP 201 body without Menu access; a different committed payload conflicts.
3. Close that session and fetch Menu's batch snapshot. One SQL statement supplies all available
   dishes and authoritative names/prices. Bound the overall HTTP call to 2 seconds.
4. Open a new PostgreSQL transaction and set local lock/statement limits (1000/3000 ms by default).
   Claim the unique key using INSERT ON CONFLICT DO NOTHING. A losing duplicate reads the
   committed winner in a separate READ COMMITTED statement and replays it.
5. Validate the integer kopeck total computed from the snapshot. Reject overflow and require equality with the
   customer's expected_total_amount. A mismatch returns 409 PRICE_CHANGED and the current total;
   it creates no reservation and leaves no committed key claim.
6. SELECT FOR UPDATE the slot. Recheck existence, cutoff and capacity. Reject snapshots older
   than 5 seconds, including network and lock waits.
7. Increment allocation; insert order/items, immutable price/name snapshots, the replay response
   and one ORDER_CREATED Outbox row. Commit everything before returning success.

No HTTP, Kafka or Telegram I/O occurs inside the write transaction. Price/capacity errors,
lock timeout and failed Outbox writes roll back all changes. Failed attempts do not reserve the
key permanently. Successful records have no automatic expiration; a later retention policy
must not permit duplicate orders during supported retries.

Order numbers use a PostgreSQL sequence formatted MAI-000001 with no daily reset. Rollbacks can
leave gaps; numbers are references, not gapless receipts. Money and quantities use signed
32-bit bounds; there are at most 100 cart lines to bound request/query work. No unconfirmed
per-dish quantity rule is introduced.

## Replays and snapshot limits

The fingerprint covers slot, normalized item IDs/quantities and expected total. Keys are scoped
to the authenticated user. Replays preserve the original creation status/version even after
preparation or cancellation; Idempotency-Replayed=true signals replay. GET returns current state.
If Menu fails while a duplicate commits, check again for that committed response before failing.
Other transient upstream/database/lock failures return a retryable 503 without allocation.

Menu and Order have no distributed transaction. The accepted snapshot may precede a subsequent
menu edit; historical orders retain their accepted names/prices. Do not claim that Menu
availability is locked until Order commits or that per-dish stock is reserved.

## Updates and cancellation

Status changes lock the order and require expected_version. Stale versions return 409. A request
for the already-current status with the current version is a no-op. A real transition increments
version once and inserts one ORDER_STATUS_UPDATED event transactionally.

Cancellation locks the order, then its slot, refreshing the slot's state after acquiring the lock.
This prevents different simultaneous cancellations from writing a stale shared counter. Check
owner/role, state, version and cutoff, decrement once and insert ORDER_CANCELLED in the same
transaction. Repeating cancellation of an already CANCELLED order acknowledges current state
without another decrement/event, including when the original version is now stale.

Creation locks a slot then inserts a new order; cancellation locks an existing order then its
slot; other state changes lock only the order. Slot administration never locks existing order
rows. Real database tests cover these concurrent paths and bounded lock failures.

## Persistence and Outbox

orders_db owns slots, orders, items, idempotency records, Outbox and the number sequence. All
foreign keys stay inside it; user/menu UUIDs are external references. PostgreSQL constraints
enforce capacity bounds, positive quantities/versions, nonnegative money, unique order numbers,
one line per dish and one event per aggregate version.

Each event has a stable UUID, type/version, UTC timestamp, order UUID and typed payload including
order_version. Cancellation emits ORDER_CANCELLED only, not an extra status event. Pending rows
have null published_at. Publication, relay retries and consumer delivery belong to Stage 4.

References: [PostgreSQL row locks](https://www.postgresql.org/docs/18/explicit-locking.html),
[ON CONFLICT](https://www.postgresql.org/docs/18/sql-insert.html),
[HTTPX timeouts](https://www.python-httpx.org/advanced/timeouts/).
