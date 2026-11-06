# Stage 4, first implementation unit — SCRUM-17

SCRUM-18 follow-up: [development topic operations and worker diagnostics](stage-4-topic-operations.md).
The SCRUM-17 evidence below is historical to its original delivery.

Status: implemented for review, 2026-11-01, following the owner's continuation request.
This is the bounded Order-owned relay unit. Notification, WebSocket and frontend runtime work
remain deferred; new storage/recipient/service-auth decisions are not approved by this unit.
Design reference: [Outbox PR #2](https://github.com/KirillBelianskiy/mai-stolovka/pull/2), head 7adf583.

## Behavior and boundaries

`python -m order_service.outbox` starts a separate process; FastAPI startup never starts it.
One dedicated PostgreSQL session owns stable advisory key `0x4D41494F55544258`, monitored on a
separate task. AUTOCOMMIT and NullPool keep that session outside SQL transactions and prevent a
locked session returning to a pool. A second worker fails closed. Lost ownership cancels dispatch;
the lock is a singleton guard, not fencing for network calls already sent.

For each aggregate, only its lowest unpublished version is eligible. The worker reads one head at
a time in a short session, validates the full v1 envelope and row IDs/type/version/time, then sends
the UTF-8 order UUID key and JSON envelope with an idempotent aiokafka producer and `acks=all`.
Stored JSON values and event IDs remain unchanged; JSONB has no original whitespace/key order to
preserve. The runtime schema is a bundled snapshot of the canonical contracts file, with byte-parity
verification in tests. No cross-service Python models or business code are imported.

Only a confirmed ACK permits a conditional `published_at` update matching the original row contents.
No SQL transaction or order/slot lock spans Kafka I/O. Failed marks retain the original event and
retry its head. Transient broker/SQL failures back off with jitter, capped at 30 seconds; waits are
interruptible by shutdown. Invalid data or permanent Kafka configuration errors stop the worker
with pending rows retained. Current general SQL failures retry; inspect recurring errors rather than
assuming retries repair missing migrations or privileges. No row purge or quarantine table is added.

The 30-second send deadline is an uncertainty boundary: a canceled wait can still leave a message
in Kafka. The worker exits rather than advancing to later versions. Producer cleanup is bounded
at five seconds, followed by separately bounded database cleanup. On unconfirmed cleanup the CLI
hard-exits with status 2 so Python cannot wait forever on background producer tasks. Normal SIGTERM
finishes bounded work and releases the guard after producer stop. Fatal errors exit 1; clean stop
exits 0. Stop/terminate the previous process before replacement; automatic failover is not provided.

Crash after ACK but before mark can produce another copy after restart, with the same ID/envelope.
Idempotent producer settings do not make PostgreSQL+Kafka atomic and do not remove cross-process
replay duplicates. Consumers still need durable deduplication and per-order version handling.
Known-attempt advancement follows versions; late lower-version copies after ambiguous sends remain
possible. No exactly-once delivery, production durability or latency guarantee is claimed.

## Explicit launch and rollback

1. Start the default local stack using the README and apply the existing Order migration explicitly.
   HTTP can create orders while Kafka/relay is unavailable; pending rows accumulate durably.
2. Provision the chosen development topic explicitly. The worker checks the topic list and refuses
   a missing topic; it never calls create_topics. Keep broker automatic topic creation disabled.
   This single-partition example is for local development only, not approved production settings:

   ```sh
   docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh \
     --bootstrap-server kafka:29092 --create --topic orders.events.v1 \
     --partitions 1 --replication-factor 1 --config min.insync.replicas=1
   ```

   Existing-topic configuration must be inspected; do not delete/recreate it to silence errors.
   Retention, production replicas/ACLs, monitoring thresholds and replay operations are SCRUM-18.
3. Starting this opt-in profile publishes ALL existing pending orders to the configured topic.
   Review that backlog before explicitly running:

   ```sh
   docker compose --profile outbox up --build outbox-worker
   ```

   The profile is not started by ordinary `docker compose up`. It has no HTTP readiness probe;
   `worker_ready` means guard acquisition, producer initialization and topic preflight, not consumer
   delivery. Its inherited HTTP-image health probe is disabled. Readiness/metrics operations remain
   a SCRUM-18 follow-up; do not interpret an HTTP health response as worker health.
4. Stop publication without deleting durable state:

   ```sh
   docker compose stop outbox-worker
   ```

   The local 60-second stop grace accommodates default deadlines; changing send/shutdown settings
   requires reviewing that grace. Never run `down --volumes` as worker recovery. Investigate exit 2
   and confirm the old process is gone before restarting. Pending rows remain available for replay.

For host development, use the Order service environment and its service-owned URL; the service
`.env.example` is a template and is not loaded automatically. Do not copy credentials into commands
or Jira. Export APP_DATABASE_URL privately, then in services/order-service:

```sh
uv sync --frozen
APP_KAFKA_BOOTSTRAP_SERVERS=localhost:9092 uv run --frozen python -m order_service.outbox
```

The image and CLI include the schema/validator, without JWT private keys or a Telegram bot token.
Kafka is plaintext local development only; no production TLS/SASL/ACL design is supplied here.

## Configuration and diagnostics

| Environment variable | Default / purpose |
| --- | --- |
| APP_DATABASE_URL | Required; only orders_db owner |
| APP_KAFKA_BOOTSTRAP_SERVERS | localhost:9092 for host, kafka:29092 in Compose |
| APP_OUTBOX_TOPIC | orders.events.v1, pre-existing topic |
| APP_OUTBOX_POLL_SECONDS | 1, empty-poll wait |
| APP_OUTBOX_SEND_TIMEOUT_SECONDS | 30, uncertain result triggers exit |
| APP_OUTBOX_SHUTDOWN_TIMEOUT_SECONDS | 5 per producer/DB cleanup phase |
| APP_OUTBOX_GUARD_INTERVAL_SECONDS | 1, guard check interval; DB query timeout uses readiness setting |

Logs use readiness/publication/retry/fatal event codes, event/order IDs and error class names, not raw exceptions,
connection URLs, full envelopes or secrets. Count/age/latency dashboards, alert thresholds and
recovery ownership remain SCRUM-18. A worker exit is not an order cancellation. Do not repair a
poison event by changing IDs, deleting pending rows or marking an unacknowledged event published.

## Verification and limitations

Local red/green evidence: initial worker tests failed at import before implementation; a later
cleanup-timeout regression failed because DB close was unbounded, then passed after a bounded
cleanup phase was added. Automated cases cover ACK-before-mark, schema/metadata rejection, stable
replay, timeout retention, guard loss/exclusion, aggregate version order despite reversed timestamps,
rollback, no SQL locks across send, and continued HTTP creation during a blocked send.

Real Kafka tests create/delete only UUID-named test topics. The crash-boundary test sends to the
actual broker, closes the first publisher before marking, then restarts and verifies copies retain
IDs/content before the next version. A separate real subprocess verifies worker startup/SIGTERM,
singleton exclusion and release. Broker stalls/errors are fault-injected; the shared broker was not
stopped. Real PostgreSQL tests use the existing isolated temporary-database runner and check Alembic
drift. CI runs them using its disposable Compose stack. No live application topic or pending live
order is published by local verification.

No Notification/Kitchen consumer is implemented by SCRUM-17, so broker ACK does not prove the
person or employee received anything. Production topology, event retention, consumer recovery,
observability and deployment remain separate decisions/tasks. The open Ruff PR #5 is preserved;
this branch also runs local Ruff warnings explicitly while that quality-gate PR awaits merge.

Sources checked 2026-11-01: [aiokafka producer semantics](https://aiokafka.readthedocs.io/en/stable/producer.html),
[PostgreSQL session advisory locks](https://www.postgresql.org/docs/18/explicit-locking.html),
[SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html).
The singleton, deadlines and halt policy are reviewable implementation defaults, not production SLOs.
