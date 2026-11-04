# SCRUM-23 — durable Notification ingestion

Status: implemented for review, 2026-11-04. Task
[#17](https://github.com/KirillBelianskiy/mai-stolovka/issues/17), stacked on Outbox/topic
PR #12 at `07f02b62907e8b725b089dd4f822a1759b9da641`, preserving #8 ancestry.
The owner explicitly approved notifications_db on existing PostgreSQL, durable event/error
storage before Kafka acknowledgment, no automatic deletion and restore/offset checks that stop
on a gap. Skill v0013 records that bounded exception. No Telegram sending is included.

## Responsibility and limits

`notifications_db` / `notifications_owner` owns:

| Table | Responsibility |
| --- | --- |
| source_checkpoints | Durable next offset by group/topic/partition |
| source_receipts | One result and key/value hashes per source location; bounded protected poison content |
| notification_inbox | Unique event ID, canonical hash/envelope and original outcome |
| order_observations | Immutable identity fingerprint, highest accepted version/status, gap/frozen flags |
| observed_versions | Substantive per-version evidence, retaining contradictory-old-copy detection |
| ready_obligations | Unique `(order_id,version)` READY purpose: PENDING, SUPPRESSED or FROZEN |

No table/ORM is imported from User or Order. An event's user UUID is not a Telegram address
or permission. PENDING is a durable candidate, not authority to send. #16/#18 still own exact
recipient/machine-auth/permission and dispatch/retry contracts. There is no bot initialization,
User lookup, scheduler, send lease, delivery receipt or Telegram HTTP call in this worker.

Only public process health remains on the HTTP shell. `/health/ready` does not prove the
standalone consumer is enabled, assigned or progressing. Worker logs distinguish partition
readiness, durable ownership and fatal stop; no envelope, raw exception, DB URL, token or
recipient ID is logged by application code. Quarantine payloads are protected DB data, not
public diagnostics. Access/backup/incident ownership still requires #28 operational acceptance.

## Validation and transaction semantics

The bundled v1 JSON Schema is byte-identical to the unchanged canonical contract. Enforce
UTF-8 JSON, no duplicate keys/NaN, closed schema/version and UUID Kafka key/aggregate agreement.
Reject payloads over 64 KiB. Quarantine stores source location, nullable verified event ID,
static reason, nullable-aware key/value SHA-256 hashes and at most 64 KiB of raw value with a
truncation flag. It never invents a verified ID from invalid content.

One short transaction locks the partition checkpoint, validates existing source receipt, claims
the event ID and serializes order observation updates. The checkpoint, receipt, inbox,
per-version observation and optional READY obligation commit together. It returns to the worker
only after DB commit; only then does the worker commit exactly `record.offset + 1` for that
partition. A failed DB write never advances Kafka. An ACK/commit failure replays durable work.

- Same source location/hash is replay. Changed bytes at an old source location, or missing
  receipt evidence behind a durable checkpoint, stops for recovery review.
- Same event ID/canonical content is replay; JSON key order is irrelevant. Same event ID with
  changed content is quarantined and freezes unsent work for both affected order IDs if needed.
- A new ID with the same substantive order/version is a duplicate version and creates no second
  purpose. Changed immutable identity or contradictory version/state is quarantined/frozen.
- Retain all accepted per-version evidence. Late older copies cannot regress the watermark.
  Known lifecycle contradictions, READY/CANCELLED forks, repeated states at distinct versions
  and impossible adjacent transitions are quarantined. Missing versions are diagnostic, not
  invented transitions; consistent gaps are accepted with `gap_observed`.
- A known COMPLETED/CANCELLED state suppresses pending READY work. A late READY after a known
  terminal observation creates no obligation. Nothing claims knowledge of an unconsumed terminal
  event or perfect freshness across a later external send.

SQL row locks serialize parallel partitions on the same order. Conflicting multiple-order
freezes acquire order locks in UUID order. No DB transaction spans Kafka, HTTP or Telegram I/O.
There is no purge, automatic repair/unfreeze or offset-reset command. Migration downgrade
refuses to discard durable responsibility; use a reviewed restore procedure instead.

## Worker lifecycle and positions

`python -m notification_service.ingest` is explicit. Default HTTP/Compose startup starts no
consumer. An optional `inbox` profile starts one process for configured group
`notification-orders-v1` and explicitly provisioned `orders.events.v1`.

A dedicated monitored PG session advisory guard excludes another worker for the same DB/group.
Guard acquisition precedes Kafka startup; guard loss cancels processing and stops the worker.
Do not bypass it or run unrelated consumers under that group. Kafka stops before the guard is
released. Unconfirmed bounded cleanup hard-exits with code 2; ordinary fatal errors exit 1;
clean SIGINT/SIGTERM exits 0. Default operation/shutdown limits are 15/10 seconds. DB statements
are bounded to five seconds with a two-second lock timeout. Contention or DB/broker failure
stops for operator restart; automatic outage retry/backoff is not implemented by this slice.

Auto-commit is off and `auto_offset_reset="none"`. Partition callbacks verify broker beginning,
end and committed positions against local durable checkpoints and explicitly seek only a verified
position. Polling waits until assignment initialization finishes. An observed assignment-generation
change can discard a stale NoOffset error from that handoff; it does not select a fallback offset.
Revocation serializes with DB/commit work; invalid/revoked commits fail and replay after restart.
Only one fetched record is processed at a time, so no later record passes a failed durable prefix.

Startup policy:

1. A new DB/group with no durable checkpoint can start only at original retained beginning zero,
   with broker committed position absent/zero. Existing broker progress without local evidence stops.
2. An existing checkpoint must be within broker retained bounds. Broker progress ahead of restored
   DB responsibility, committed position below retained beginning, or DB position beyond broker
   end stops. Do not silently seek latest.
3. Broker progress behind durable DB responsibility replays from the valid broker position. If the
   broker has no position but complete history is retained from zero, explicitly replay from zero;
   source/event/version dedup retains one purpose. Missing broker position with truncated history
   stops. This is a local conservative recovery policy, not production RPO/RTO approval.

Kafka numeric offsets need not be dense (for example control records). The worker processes
Kafka's delivered sequence; contiguous responsibility means no earlier *delivered* record is
unowned, not an invented requirement to receive every integer offset. Retention gaps are checked
against broker bounds, with out-of-range errors failing closed during consumption. Source hashes
detect changed known locations, but do not prove topic incarnation after total DB/group history
loss. Topic deletion/recreation is not a supported recovery shortcut.

## Explicit local setup

For a fresh disposable stack, `infra/create-local-env.py` now generates an independent Notification
password and PostgreSQL initialization creates its restricted owner/database. It revokes PUBLIC
connect/schema-create access as for the existing services. The normal stack still starts only the
HTTP shell; the inbox profile is opt-in.

For an **existing volume**, add a new independent `NOTIFICATIONS_DB_PASSWORD` to the ignored
mode-0600 `.env`; do not replace other values or delete volumes. Then:

```sh
python3 infra/provision-notification-db.py
docker compose build notification-service
docker compose run --rm --no-deps --entrypoint /app/.venv/bin/alembic notification-service upgrade head
python3 infra/kafka-topic.py --check
# Inspect pending history/consumer readiness before deliberately starting application ingestion:
docker compose --profile inbox up -d notification-inbox
```

The provisioning tool creates/checks only the Notification owner/database, rejects unsafe owner
flags or a different DB owner, and never resets an existing password, migrates application tables,
launches a worker or publishes an event. Passwords arrive through container environment, not
command arguments or tool output. A failed check emits a sanitized failure, not captured SQL.
Existing-role password/privilege drift needs private operator investigation, never volume reset.

This task provisioned the local empty Notification logical DB and role for isolated-test ownership;
it did **not** apply inbox migrations to that application DB or execute the application-start
command above. Tests use separate UUID-named DBs/topics/groups only.

## Recovery and operator inspection

Stop intake before restoring; dispatch remains absent/disabled. Back up all six Notification
tables consistently and retain evidence at least through approved replay/backup windows.
No automatic deletion is implemented. After restore, inspect group/topic identity, retained bounds,
broker position, durable checkpoint and receipts. The worker's checks enforce the policies above;
do not edit checkpoints forward to make them pass. If required history expired, preserve the
incident and obtain a reviewed backfill/reconciliation plan. #28 owns an actual backup/restore
exercise, RPO/RTO, disk capacity, alert routes and production access/retention approval.

Within the private Notification DB, operators can inspect sanitized receipt metadata with:

```sql
SELECT topic, partition, "offset", outcome, reason, truncated
FROM source_receipts WHERE outcome = 'QUARANTINED' ORDER BY received_at;
SELECT group_id, topic, partition, next_offset FROM source_checkpoints;
SELECT state, count(*) FROM ready_obligations GROUP BY state;
```

Do not publish raw quarantine payloads or credentials. Do not rewrite published events, create
fresh IDs to bypass dedup, unfreeze conflicts blindly or treat PENDING as permission to send.

## Verification evidence

Acceptance was specified before implementation. Initial domain tests failed importing absent
`notification_service.domain.events`; they now pass. Integration tests were written before the
store implementation but no pre-implementation PG red is claimed for tests not then executed.

The first standalone-process probe exposed an initial Kafka assignment race: polling could see
NoOffsetForPartitionError before callback seek completed. Verified-assignment readiness/generation
handling fixed it; the actual standalone regression now passes. An unsupported aiokafka option
was removed after checking the installed 0.15 API, not hidden behind an untested compatibility shim.

| Check | Actual local result |
| --- | --- |
| Frozen Notification sync / lock | Added PostgreSQL/Alembic/schema dependencies; frozen install passed |
| Notification non-integration tests | 17 pass: parser/schema/key/size/duplicate keys, canonical hashes/lifecycle, bundled schema equality, DB-before-offset and failed-prefix/assignment guards, existing process health |
| Isolated real PG/Kafka Notification tests | 16 pass, including duplicate/concurrent sources and versions, redirected ID conflicts, terminal suppression, poison/rollback, source reuse/restore checks and DB-role isolation |
| Real broker/process probes | DB-commit-before-broker-commit restart replay, durable poison before ACK, failed n with n+1 fetched, actual broker-ahead recovery stop, actual delete-records retention gap stop, singleton exclusion, guard termination, restart and SIGTERM |
| Other isolated services | User 5, Menu 14, Order 30 passed on this #12-based branch; Notification-specific later reruns did not alter their runtime |
| Alembic drift | Passed for all four services on their exercised isolated runs |

Real retention deletion and group resets occur only on generated `mai-test-inbox-*` resources.
No application topic, pending application order, live recipient or Telegram send is used.
The runner drops only its generated test DBs; tests stop child consumers and delete their own
topics/groups. Existing Starlette/httpx TestClient deprecation warning remains. Final lint/format,
image/config checks, resource inventory and PR-head CI are recorded in the PR handoff.

No claim of production readiness, actual backup restore, real-user delivery, throughput or complete
#18 acceptance follows. No merge/deployment or blanket approval of remaining D2–D10 decisions.

Sources checked 2026-11-04: [aiokafka manual commits/positions/rebalance](https://aiokafka.readthedocs.io/en/stable/consumer.html),
[PostgreSQL 18 row locks](https://www.postgresql.org/docs/18/explicit-locking.html). Installed
aiokafka 0.15 fetcher/coordinator source was checked for the assignment race. Project v1 event
contract and order lifecycle remain authoritative; documents do not invent another service's authority.
