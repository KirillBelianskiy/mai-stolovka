# Domain events and delivery

Status: Stage 3 persists validated v1 events atomically with order changes. The envelope and payload schemas are finalized for this producer; Kafka topic policy remains proposed. No relay, consumer, retry worker, or Telegram sender is implemented.

## Envelope

`packages/contracts/events/envelope-v1.schema.json` uses JSON Schema 2020-12. All six fields are required:

| Field | Meaning |
| --- | --- |
| event_id | UUID identifying the committed event; preserved across retries |
| event_type | ORDER_CREATED, ORDER_STATUS_UPDATED, or ORDER_CANCELLED |
| event_version | Integer 1 for this contract |
| occurred_at | UTC RFC 3339 timestamp |
| aggregate_id | Order UUID; also the Kafka message key |
| payload | Closed event-specific object described below |

Payloads contain `order_number`, `user_id`, `slot_id`, `status`, `total_amount` (kopecks), and
`order_version`. Updates/cancellation also contain `previous_status`. Creation has PENDING/version 1;
updates follow the approved state machine, and cancellation records the prior PENDING/PREPARING state.
Examples are illustrative values, validated against the schema. Actual persisted envelopes are
also validated in PostgreSQL integration tests. No credentials or full user profiles are included.

Consumers dispatch by type/version and reject unsupported versions. The envelope and payloads are
closed; new fields or breaking changes require versioned contracts and a documented migration.
There were no consumers of the earlier provisional scaffold when its v1 payload was finalized.

The proposed initial stream is one `orders.events.v1` topic so each order's events share a key and partition. Partition count, retention, topic creation policy, and consumer access remain open. `order_version` gives the per-order sequence. Kafka ordering is per partition; it does not provide a global order or make PostgreSQL writes transactional with Kafka.

## Transactional Outbox

Order Service inserts each business change and an outbox row in one PostgreSQL transaction. The complete envelope, event ID, aggregate version and timestamp are stored, with `published_at` initially null. No worker currently changes that field. A future separately runnable relay must publish only committed rows and mark them delivered after broker acknowledgement. A crash after acknowledgement but before marking produces a duplicate; never generate a fresh event ID for that retry. Multiple relays must coordinate safely and preserve each aggregate's event sequence; `SKIP LOCKED` alone does not guarantee publication order.

Broker outages leave committed events pending for retry. Bound retry delays and expose backlog age/count and failures when the relay is implemented. Kafka delivery is at least once; no exactly-once processing claim is made.

## Consumer processing and notification caveats

Consumers persist deduplication/processing state before committing offsets according to an agreed durability design. Commit only when processing has completed or responsibility has been transferred durably to a retry mechanism. Retry transient errors with bounded backoff; honor Telegram retry-after responses. Malformed events, unsupported versions, and permanent recipient errors require an explicit quarantine/dead-letter policy rather than a blocking infinite loop.

Notification Service has no relational DB in Stage 1. Its later implementation must select durable retry and deduplication state, for example Kafka-backed retry/state topics with recovery semantics, or an explicitly approved service-owned store. An in-memory set, filesystem without a persistent recovery design, or Kafka offsets alone is insufficient for scheduled retries and event-level deduplication.

Telegram send operations and consumer state cannot be committed atomically. A crash after a successful send but before recording success can produce a duplicate message; acknowledge that residual window rather than promise exactly-once user-visible delivery. The bot also needs a valid user interaction/write permission path and a durable recipient association; merely knowing a Telegram user ID is insufficient.

## WebSocket consumer groups and recovery

Start with a single WebSocket Service instance. Replicas sharing one Kafka consumer group split partitions, so an event would reach only one replica while clients connected to other replicas could miss it. Per-instance groups can broadcast the stream to all instances at the cost of group lifecycle, replay, and load management. Adopt that option only when replicas are needed.

Native WebSocket clients must reconnect with backoff and fetch canonical current orders through authorized REST. WebSocket events are hints about changes, not durable client state. Subscription setup and REST reconciliation need a race-safe protocol before implementation. Staff JWT transport, expiration, revocation, allowed origins, and roles remain open; never put an unauthenticated kitchen stream into the bootstrap.

Reference: [Kafka consumer design and guarantees](https://kafka.apache.org/41/design/design/).
