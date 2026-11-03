# Stage 4 Outbox operations and monitoring — SCRUM-18

Status: proposal for owner review, 2026-11-03. This document defines an operational design for
the separately launched SCRUM-17 worker. SCRUM-18 PR #12 adds development topic provisioning and
structured diagnostic logs; this document distinguishes those local signals from production
monitoring, alert routing, and recovery ownership. It does not add runtime behavior. Worker
implementation reference:
[SCRUM-17 Outbox worker guide](https://github.com/KirillBelianskiy/mai-stolovka/blob/35915fa6a1f1454a0d5d22c092aaa3822f9a4cbe/docs/stages/stage-4-outbox.md).
Related local diagnostics implementation: [SCRUM-18 PR #12](https://github.com/KirillBelianskiy/mai-stolovka/pull/12),
head `07f02b6`. The proposal baseline is product main `4fb6886` plus the separately reviewed
SCRUM-17/#12 behavior; #12 is stacked on #8 and has not merged.

## Scope and operating assumptions

Order Service persists order changes and Outbox rows in one PostgreSQL transaction. The optional
worker publishes pending rows to an explicitly provisioned Kafka topic. PR #12 adds periodic
structured-log samples for pending count/age, process-local attempt/ACK/mark/retry counters, last
ACK latency, last post-mark success, and Boolean backlog-age/retry-streak indicators. It does not
add a metrics endpoint, durable counters, external alert routing, disk-capacity monitoring, or
consumer-lag monitoring. A Kafka ACK means broker acknowledgment, not that Notification, Kitchen,
or a person received the event. All thresholds, retention choices, on-call ownership, and production
targets below are proposals, not approved service objectives.

Keep API health independent of relay health: order creation can continue while Kafka is unavailable,
and the durable backlog will grow. This protects transaction correctness but does not make an
unbounded outage harmless; PostgreSQL disk capacity and eventual replay rate still bound recovery.
Do not add a second relay or automatic failover until singleton and ambiguous-send recovery have
been reviewed.

## Signals and proposed alerts

Use bounded-cardinality dimensions (environment, topic, worker instance, outcome class). Do not put
order IDs, event IDs, user IDs, exception messages, database URLs, or credentials in metric labels.
Identifiers may appear in access-controlled structured logs where needed for one-event investigation.

| Signal | Meaning | Proposed alert / response |
| --- | --- | --- |
| Pending row count | PR #12 logs a sampled durable count; it is not a durable metric or trend store | Add external trend/threshold evaluation only after selecting a collector and capacity-based threshold |
| Oldest pending age | PR #12 logs sampled age and `backlog_alert` at its configured threshold (default 60 seconds) | The Boolean is not a routed alert; proposed warn at 60 seconds and page at 5 minutes sustained, subject to an accepted delivery objective |
| Publish ACK rate and latency | PR #12 logs process-local ACK totals and last successful ACK latency | No rate window or zero-ACK-duration alert exists; proposed alert after 2 minutes with pending work and no ACK, subject to measurement |
| Publish retry count and last success | PR #12 logs process-local retries, post-mark last success and `retry_alert` after a continuous retry streak (default 300 seconds) | The Boolean is not a routed alert; configure external notification only after owner selects route and response target |
| Worker process / guard owner | PR #12 logs guard loss and process termination classes; no independent monitor proves the worker is enabled or alive | Alert if no expected worker while enabled; if two instances are attempted, investigate instead of bypassing guard |
| Invalid event / permanent broker error | Fatal class is logged and the worker stops with the row pending | Immediate stop-and-page is a proposed external response, not implemented routing |
| DB mark failures after ACK | Counters can show ACKs exceeding durable marks; no dedicated alert is emitted | Add a discrepancy alert only with a defined sampling window; replay can duplicate, so preserve event IDs |
| PostgreSQL free space / growth | Not measured by PR #12 worker diagnostics | Proposed warn at 30% free and page at 15% free (provisional); requires platform volume-capacity signals |
| Consumer lag and replay horizon | Not measured by the producer worker or local topic tool | Consumer owners need independent lag/retention alerts before business delivery is claimed |

PR #12's `backlog_alert` and `retry_alert` fields are diagnostic Booleans in logs; they do not send
notifications or establish an SLO. Its counters reset on process restart and its backlog query is
a point-in-time sample separate from publication counters. Threshold examples in this proposal are
external alert recommendations, not behavior present in #12. Before production, derive them from the accepted
delivery objective, expected order volume, database headroom, broker performance and a measured
replay rate. Do not alert on process liveness alone as proof that publication is progressing.

## Diagnosis and recovery runbook

1. **Confirm the symptom.** Check worker exit code and sanitized logs, pending count/oldest age,
   last successful publish, PostgreSQL health/free space, broker availability, topic existence and
   permissions. Determine whether the process is enabled intentionally. Do not use HTTP API readiness
   as a proxy for worker health.
2. **Transient broker or database outage.** Leave HTTP order writes running while PostgreSQL has
   safe headroom. The worker retries transient failures. Restore the dependency, confirm ACKs resume
   and pending age/count trend down, then verify the oldest remaining event is not stuck. If storage
   headroom becomes unsafe, the service owner must decide whether to pause order intake; never delete
   events or change published markers to relieve pressure.
3. **Missing topic or authorization/configuration failure.** Stop/refrain from restarting in a loop.
   Confirm the configured topic, broker endpoint, credentials/ACLs and existing topic configuration.
   Provisioning or changing retention/partition settings requires its own reviewed operational
   procedure. Do not allow automatic topic creation or silently route to another topic.
4. **Invalid or conflicting persisted event.** Keep the worker stopped and preserve the row and
   evidence. Compare the row metadata and envelope to the canonical v1 schema and originating order
   history. Propose a reviewed repair with audit evidence; do not edit IDs, skip the aggregate head,
   mark it published, or delete it as an ad hoc recovery.
5. **Ambiguous send, exit code 2, or uncertain cleanup.** Verify the old process has terminated and
   released its session guard before replacement. A message might already be in Kafka; restart
   republishes the same event ID and content. Consumers must deduplicate durably. Do not start a
   second worker to “unstick” publication.
6. **Backlog recovery.** Start one worker using the documented opt-in command after confirming the
   topic and expected backlog. Observe ACKs, DB marks, oldest pending age, retry rate and disk headroom.
   Keep the worker running until the backlog falls and new work continues to publish. If age/count
   does not improve, stop and investigate rather than increasing concurrency without an ordering and
   fencing design.
7. **Close the incident.** Record the affected time range, cause, duplicate/loss assessment, number
   of pending/replayed records, actions and remaining risks. Confirm consumers have resumed and
   reconcile any consumer-specific lag under their own runbooks; a producer ACK alone cannot prove
   downstream processing.

Never use volume deletion, Outbox purging, offset resets, topic recreation, or manual `published_at`
updates as generic recovery steps. Each can destroy the only recovery evidence or create silent loss.

## Backup, retention, and replay boundaries

Outbox rows are currently retained without automatic cleanup. A PostgreSQL backup must include the
orders, idempotency and Outbox state consistently; recovery objectives and restore validation remain
owner decisions. Kafka retention is a separate bounded replay window and is not a backup. A database
restore can republish events already present in Kafka, while a topic retention expiry can make old
events unavailable to a new consumer. Consumers require their own durable deduplication, replay and
offset recovery procedures before production use.

Do not propose compaction or retention reduction for `orders.events.v1` without assessing consumer
replay requirements and partition/order behavior. Do not delete Outbox rows merely because the broker
has acknowledged them until archival, audit, idempotency retention and disaster recovery are agreed.
Any future archival/purge job needs a separate reviewed design with measurable recovery guarantees.

## Rollout and rollback

- Keep the worker opt-in and run exactly one instance. Verify the approved topic and broker
  configuration, database backup status, available disk headroom, operator access and downstream
  consumer readiness before enabling publication.
- Record baseline pending count/oldest age and current worker version. Start the worker using the
  SCRUM-17 runbook; verify guard acquisition, producer initialization, first ACK/mark and expected
  metrics/log events. Increase exposure only after sustained progress and incident ownership are
  established.
- To roll back, stop the worker cleanly. Leave order writes and pending rows intact. Investigate
  the reason before restart; replay can produce duplicates with stable IDs. Do not roll back by
  deleting topics, volumes or Outbox rows.
- Any production rollout also requires approved broker durability, TLS/SASL/ACLs, topic
  partitions/replication/retention, database backup/restore, secrets rotation, alert routing,
  incident owner and recovery objectives. Local plaintext single-node Compose is not production
  evidence.

## Owner decisions and implementation acceptance

Owner approval is required for: delivery/freshness objective; alert thresholds and routes; PostgreSQL
disk reserve and intake-pause criteria; backup/restore RPO/RTO and restore tests; Kafka topology,
security and retention; consumer lag/replay responsibilities; Outbox archive/purge policy; and named
incident ownership. No recommendation here approves new infrastructure or changes the existing
event schema.

When implementation is authorized, acceptance should show that: signals distinguish process health
from publication progress; pending age/count and last ACK are observable without high-cardinality
labels or sensitive data; retry/poison/guard-loss/ambiguous-send alerts fire in controlled tests;
recovery preserves row IDs and payloads; one worker is enforced; backup restore preserves event and
idempotency state; and a recovery exercise demonstrates duplicate-safe consumer reconciliation.
These are future acceptance criteria, not checks performed by this design.

## Sources

Project-specific behavior is referenced from SCRUM-17 at the exact head above and the existing
Stage 3 Outbox contract in `docs/architecture/events.md`. This proposal adds operating guidance only;
thresholds and recovery objectives require owner evidence and approval.
