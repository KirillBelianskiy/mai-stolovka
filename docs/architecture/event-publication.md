# Stage 4 Outbox publication design — SCRUM-13

Status: proposed design for owner and SCRUM-14 consumer review, 2026-10-31. No relay, migration,
topic or runtime configuration is implemented by this document. Owner: kirill_bel. Product baseline:
4fb6886. Coordination: SCRUM-12; notification counterpart: SCRUM-14 (bobr2610).

## Boundary and recommendation

Order Service remains the sole writer of orders and their events. A separate executable worker
within that service owns publication using its own orders_db connection and Kafka producer.
HTTP order creation must not depend on broker availability. Keep the complete stored v1 envelope
and event_id unchanged on every attempt. Notification and WebSocket own separate consumer groups;
neither reads orders_db. The wire schema in packages/contracts is unchanged.

Recommend one serial relay instance initially. At this workload a sharded relay/CDC platform adds
coordination that is not yet justified. Poll pending rows in short DB transactions; perform no
Kafka call while holding business row locks or a SQL transaction. A dedicated session-level
PostgreSQL advisory lock guards against accidentally starting another relay, not against order
creation. Use an explicit stable lock namespace/key, not Python's randomized hash. Release on exit.
This is a singleton guard, not distributed fencing or a promise of exactly-once delivery.

## Publication algorithm

1. Acquire the singleton guard on a dedicated, monitored database connection. If unavailable,
   do not publish. Start the producer with idempotence enabled and acks=all.
2. Read up to 100 pending events in a short transaction. A row is eligible only when no lower
   unpublished aggregate_version exists for its aggregate_id. Sort eligible heads by occurred_at,
   aggregate_id, aggregate_version. Never use created timestamp alone to infer order versions.
3. Validate the stored envelope against v1, including equality of event ID, aggregate ID, type and
   payload order_version with row metadata. Serialize UTF-8 JSON; use the order UUID string as key.
4. For one candidate, send and await broker acknowledgment. After ACK, execute a short conditional
   update setting published_at only if still null. Only then advance that aggregate to its next
   version. A failed DB mark must retry the same event, never generate a new one.
5. On transient send or mark failure, stop advancement and retry with exponential backoff/full
   jitter (proposed 1 second base, 30 second cap). Empty polling waits 1 second. Shutdown interrupts
   the wait. Pending rows are the durable retry queue; an in-memory delay is not durable progress.
6. On lost singleton/DB session or ambiguous producer shutdown, stop new sends and exit. Start
   replacement only after terminating the previous process; automatic concurrent failover is not
   part of the first implementation. Close producer before relinquishing the guard on clean exit.

In idempotent aiokafka mode, a batch may outlive request_timeout_ms. Propose a 30-second application
send deadline; cancellation does not prove the send was aborted. On deadline, do not mark the row
or send later versions: shut down that producer under a separate bounded cleanup deadline and exit.
If shutdown cannot be confirmed, operations must terminate the old process before replacement.
Restart republishes the pending event with its original ID. No Kafka transaction spans PostgreSQL.

During normal operation, an aggregate's first acknowledged publications advance by version. Crash,
ambiguous timeout and replay windows can still produce duplicates, including a late lower-version
copy. Consumers must tolerate event_id duplicates and compare order_version; never claim the raw
stream is globally ordered, or that a singleton advisory lock fences an already-sent network call.
The singleton is an initial availability tradeoff: a stalled relay can delay other orders, while
HTTP writes continue safely. Add concurrency only after measuring backlog and designing fencing.

## Failure outcomes

| Failure point | Durable outcome / recovery |
| --- | --- |
| Before business commit | No event visible; nothing to publish |
| After business commit, before send | Pending row survives; worker retries |
| Broker rejects or is unavailable | No DB mark; retries/backoff; order HTTP stays independent |
| ACK is lost / send deadline expires | Broker may already contain event; restart retries same ID |
| ACK arrives, worker crashes before DB mark | Duplicate on restart; consumer dedup is required |
| DB mark commits, worker crashes | Row remains published; next version becomes eligible |
| Malformed persisted event / permanent broker configuration error | Stop and alert; keep row pending, no silent skip or falsely successful mark |

For the first relay, poison data/configuration halts publication rather than losing events. An
operator investigates and proposes a reviewed repair that preserves audit history and IDs. Future
per-aggregate quarantine can isolate failures, but requires its own persisted state/ordering design.
Do not delete pending events or advance offsets as an implicit dead-letter policy.

## Proposed Kafka contract and operations

| Item | Proposed initial setting / rule |
| --- | --- |
| Domain topic | orders.events.v1; explicit provisioning, automatic topic creation disabled |
| Key/value | UTF-8 order UUID / exact stored v1 JSON envelope |
| Local partitions/replication/min ISR | 1 / 1 / 1, strictly disposable development durability |
| Production partitions/replication/min ISR | Proposed 3 / 3 / 2, gated on actual infrastructure approval |
| Retention | Proposed 7 days, cleanup.policy=delete; never compact the domain history topic |
| Consumer groups | notification-orders-v1 and kitchen-orders-v1, independent offsets |
| Consumer contract | Validate type/version/IDs; persist or transfer retry responsibility before offset commit |

Do not increase partition count in place without an ordering/migration plan; a key can move to a
different partition. Retention is a bounded replay window, not a backup. Do not purge Outbox or
idempotency records in this stage. Production outage/replay objectives, authentication/ACLs and
retention require owner approval. Retry/quarantine topics and consumer durability belong to
SCRUM-14; this proposal does not provision or approve them.

Worker liveness reports process availability; readiness should require DB connectivity, acquired
guard and producer initialization, independent of HTTP readiness. Expose pending count/oldest age,
ACK rate/latency, retry count, last success, singleton loss and invalid-event failures. Proposed
local alerts: pending age >60 seconds or repeated errors >5 minutes, to be tuned using measurements.
Structured logs contain IDs/versions and sanitized error classes, never credentials or user profiles.
On rollout, verify topic/settings and restore/backup policy, run one worker, measure backlog, and
stop the worker to roll back delivery; order writes and persisted pending rows remain intact.

## Alternatives and approval gates

- Reject direct Kafka publication inside order transactions: it couples broker availability to
  reservations and cannot atomically commit Kafka with PostgreSQL.
- Defer Debezium/CDC and multi-relay leases/sharding: operational components and fencing are
  disproportionate to the current unmeasured workload. Revisit with observed backlog evidence.
- Reject SKIP LOCKED alone as an aggregate-ordering mechanism: two workers can select successive
  versions and finish sends in the opposite order.

Before implementation approve singleton availability/poison policy, retry/deadline values,
production topology/retention/ACLs, and SCRUM-14's durable responsibility/offset contract. Existing
v1 events carry user_id but no Telegram recipient; user permission/recipient lookup is a separate
User–Notification interface proposal, not an implicit payload change.

## Implementation-ready acceptance scenarios

Future implementation should demonstrate with PostgreSQL and Kafka integration tests:

1. A rolled-back order never publishes; a committed order publishes while HTTP remains independent
   of a broker outage. Pending rows survive worker restart.
2. Fault injection at send/ACK/DB-mark boundaries produces no loss; any duplicates retain event_id
   and envelope. A completed DB mark prevents routine republishing.
3. Two attempted relay processes result in one publisher; losing its guard halts new sends.
4. Version n+1 is not intentionally sent before n is acknowledged and marked; consumers safely
   handle duplicate or late lower-version copies after an ambiguous restart.
5. Send timeout does not falsely mark success or advance later versions. Shutdown/restart is bounded.
6. Invalid envelopes halt/alert with the row retained; no destructive repair or silent skip occurs.
7. Topic key and schema match the contract; Notification and Kitchen groups each receive the stream.
8. Backlog metrics/alerts and graceful shutdown work without leaking tokens or DB URLs.

These are future acceptance tests, not tests executed for this design. The implementation backlog
should split worker/guard lifecycle, publish/mark loop, topic provisioning/observability, and fault
injection/consumer integration, dependent on the owner decisions above.

## Sources and review status

Official sources checked 2026-10-31: [Kafka delivery/consumer design](https://kafka.apache.org/41/design/design/),
[aiokafka producer semantics](https://aiokafka.readthedocs.io/en/stable/producer.html),
[PostgreSQL session advisory locks](https://www.postgresql.org/docs/18/explicit-locking.html).
Kafka 4.1 design is used for stable delivery concepts; installed local Kafka is 4.4.0 and its exact
configuration compatibility must be checked before implementation. Counterpart agreement and owner
approval are pending; this proposal alone does not establish a final consumer contract.
