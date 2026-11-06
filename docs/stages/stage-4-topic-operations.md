# SCRUM-18 — development topic operations

Status: local operations and probe acceptance implemented for review, 2026-11-03. The owner requested continuing the recorded
backlog order. This branch is stacked on SCRUM-17 head `35915fa`; it does not merge that PR.
Full SCRUM-18 acceptance remains incomplete.

## Backlog and skill reconciliation

The current execution index is [MVP #13](https://github.com/KirillBelianskiy/mai-stolovka/issues/13),
with this reconciliation tracked in [#15](https://github.com/KirillBelianskiy/mai-stolovka/issues/15).
Issue #10 is the active coordination channel; #9 is the historical connectivity trial.
Skill v0010 resumed collaboration: Mac owns this runtime/guide; Bobr owns the separate
operations proposal and independently reviews the runtime. Skill v0011 assigns the MVP backlog.

[Design integration PR #4](https://github.com/KirillBelianskiy/mai-stolovka/pull/4), head `5ffed86`,
records the suggested order: SCRUM-22 and 17/18, then 23/24, then 19/20. Frontend foundations
25/27 can proceed against existing APIs, followed by 26/28. SCRUM-17 is implemented in
[PR #8](https://github.com/KirillBelianskiy/mai-stolovka/pull/8). SCRUM-18's local operations slice
can start independently of new recipient credentials or Notification storage; consumer durability
and production operations remain dependencies of the full ticket.

The installed `mai-food-codex-skill` v0009 records the original bounded SCRUM-18 continuation;
v0010/v0011 supersede its sequential-only coordination, preserving v0008 as SCRUM-17 history.
The current request does not settle every D1–D10 policy. Retain the
service boundaries, test-first workflow and no-merge/deployment rules.
The local mailbox skill concerns read-only agent dialogue, not application implementation.
The generic Forge skill is a generator and needs no modification for this work.

## Cross-review for MVP issue #15

Mac reviewed Bobr's [PR #11 at fddd582](https://github.com/KirillBelianskiy/mai-stolovka/blob/fddd582de3a2f9af71d6bfed247e51fe7fd0d75a/docs/stages/stage-4-operations.md)
against runtime [PR #12 at 07f02b6](https://github.com/KirillBelianskiy/mai-stolovka/pull/12)
and its tests on 2026-11-03. Bobr's document was read only; no blocking mismatch was found in
the reviewed signal/recovery boundaries. This is an independent review of Bobr's proposal,
not independent review of Mac's own runtime or owner approval of operational policy.

| Boundary | Reconciled meaning / evidence |
| --- | --- |
| Readiness | `worker_ready` follows guard acquisition, producer start and a guard check; it precedes the first send and proves no ACK, durable mark or downstream delivery. HTTP readiness is separate. |
| Backlog | `pending_count` / `oldest_pending_seconds` are bounded SQL samples; `backlog_alert` is a log Boolean, not paging. Sample failure emits `backlog_unavailable` without publishing or modifying rows. |
| ACK versus mark | `acks_total` increments after broker return; `published_total` and `last_success` advance only after the conditional DB mark. Tests cover ACK followed by failed mark and stable-ID replay. |
| Retry | `retries_total` is process-local; `retry_alert` reflects a continuous failure streak, reset by a successful relay iteration. Neither supplies a durable rate window or alert route. |
| Guard / poison / ambiguity | Guard loss stops dispatch; invalid envelopes retain pending state. Exit 2 indicates unsafe cleanup: confirm old-process termination before replacement. Never skip/delete the head, reset offsets, or manually mark publication to recover. |
| Production monitoring | Disk headroom, zero-ACK windows, consumer lag, external alerts, backup/restore objectives and operators remain proposals in #11 and dependencies of #28. |

Review verification: 15 root contract/topic tests and 57 Order non-integration tests passed;
30 integration cases were deselected in this review, not rerun. The existing Starlette/httpx
deprecation warning remains. No worker, application topic, customer order or bot send was started.
The initial `uv run --frozen` attempts could not access the host cache; the checks above used
the existing project virtual environments directly, without reinstalling dependencies.

GitHub Actions checks inspected at the exact #11/#12 heads passed (including integration):
[#11 run](https://github.com/KirillBelianskiy/mai-stolovka/actions/runs/41709084227),
[#12 run](https://github.com/KirillBelianskiy/mai-stolovka/actions/runs/41704814230).
Cloudflare Pages checks failed on both heads. Their cause is not established here; existing-domain
assessment belongs to #25. These heads therefore do not have all external checks green.

Review-record correction, 2026-11-04: Bobr already reported the independent read-only runtime
review at exact head `07f02b62907e8b725b089dd4f822a1759b9da641` in
[issue #10](https://github.com/KirillBelianskiy/mai-stolovka/issues/10#issuecomment-6614144173).
It distinguishes implemented local diagnostics from external paging/disk/lag/durable metrics and
reports no blocking mismatch. His later
[document reconciliation](https://github.com/KirillBelianskiy/mai-stolovka/issues/10#issuecomment-6614189361)
complements that review. The earlier request for another identical runtime review overlooked
this existing coordination record; no duplicate review is required merely because it is outside
#12's timeline. This acknowledges Bobr's recorded review, not a claim that he reran tests locally
or approved production operations. Mac's independent #11 review remains separately attributed.
Full SCRUM-18 additionally waits for durable Notification/Kitchen consumers (#17/#24) and
approved production topology/security/retention/restore/monitoring (#25/#28). Do not close it
based on local probes or documentation agreement.

## Development topic tool

From the repository root:

```sh
python3 infra/kafka-topic.py
python3 infra/kafka-topic.py --check
python3 infra/kafka-topic.py --create-dev
```

The default invocation only prints a plan and makes no Docker or broker calls. `--check` runs
Kafka's topic description command in the existing Compose broker. `--create-dev` explicitly
creates the topic if absent, then checks the resulting state even if the topic already existed.
No tool invocation starts the Outbox worker, consumes records, or resets group positions.

Reviewable local development defaults match the producer design: `orders.events.v1`, one
partition, replication factor one, explicit `min.insync.replicas=1`, `cleanup.policy=delete`
and seven-day `retention.ms=604800000`. These are development settings, not approved production
durability or replay objectives. Retention is a bounded history window, not a backup.

Validation requires the exact topic and topology, explicit settings, and its single replica
online as leader and ISR. Missing metadata, unavailable brokers and configuration drift fail
closed. Existing mismatches are not altered, deleted or recreated. In particular, an older
manually provisioned topic without explicit retention will fail the check, even if the broker's
current inherited default happens to match. Review any remediation separately.

Commands use the fixed local Compose service, no shell, a 60-second timeout and sanitized error
messages. Ordinary Compose startup stays unchanged and automatic topic creation stays disabled.

## Acceptance and evidence

Define acceptance before implementation: plan mode makes no broker call; create is explicit and
idempotent for matching topics; topology/configuration/unavailable-replica mismatches are rejected;
existing drift never triggers repair; failed commands stop; subprocess calls are bounded.

- Red: the new test module failed because `infra/kafka-topic.py` did not exist.
- Green: nine focused topic test methods pass, including eight drift subcases and three malformed
  metadata subcases. Two additional integration tests execute the real bundled Kafka CLI on
  UUID-named disposable topics: create/check/repeated create, and existing retention drift refusal.
- All 15 root contract/operations tests pass. Root Ruff checks (including W), formatting and
  `git diff --check` pass. The new tests run in the existing contracts CI job's
  discovery command without additional CI configuration.
- During the first slice Docker was unavailable: `docker compose ps --format json` could not connect to the daemon.
  The real `--check` invocation also exited 1 with a sanitized failure. Default plan mode succeeded
  without Docker. On continuation Docker became available; only PostgreSQL/Kafka were started.
- Diagnostics red: `test_outbox_diagnostics.py` failed importing the absent `report_backlog`;
  the sustained-retry test later failed because the retry alert field was absent. Both now pass.
- Order non-integration suite: 57 passed. Ruff including W, full service formatting and strict
  Mypy pass. Existing Starlette/httpx test-client deprecation warning remains.
- Isolated runner: User 5, Menu 14 and Order 30 integration tests passed, with Alembic drift
  checks. The new real PostgreSQL snapshot test verifies empty, two pending, one pending, empty.
  Independent probes verify exact keys/envelopes, separate committed offsets and valid-offset
  restart despite a latest fallback. These are probes, not production Notification/Kitchen consumers.
- The first integration run failed in test cleanup because aiokafka has no group-deletion method.
  Cleanup now uses the bundled Kafka CLI and nested finalizers. This was a test defect, not a
  product red result. Exact leaked test resources were removed; subsequent checks pass.
- Default and opt-in Compose configurations validate. The changed Order image builds and imports
  the standalone worker/diagnostic settings. Final resource inspection finds no temporary test
  databases, topics or consumer groups; only Kafka's internal offsets topic remains.

## Publication and backlog diagnostics

The opt-in worker emits `outbox_metrics` immediately after startup and periodically thereafter.
Each sample uses a separate read-only aggregate query over unpublished Outbox rows. It reports
`pending_count` and nonnegative `oldest_pending_seconds`; empty backlog has zero age. The query
has the configured readiness deadline and never holds a transaction across broker I/O.

Process-local counters report attempts, broker ACKs, durable marks and retries separately.
`ack_latency_ms_last` measures the last successful broker wait using a monotonic clock;
`last_success` is a UTC timestamp set only after the database mark. Counters reset on process
restart and are not durable totals. An ACK followed by a failed mark can increase ACKs without
increasing published count. The SQL snapshot and process counters are observational, not one
atomic snapshot or an external delivery receipt.

| Setting | Default / meaning |
| --- | --- |
| APP_OUTBOX_METRICS_INTERVAL_SECONDS | 30; interruptible interval between bounded samples |
| APP_OUTBOX_BACKLOG_ALERT_SECONDS | 60; `backlog_alert=true` when oldest pending age exceeds it |
| APP_OUTBOX_RETRY_ALERT_SECONDS | 300; `retry_alert=true` after a continuous retry-error streak |

A successful relay iteration resets the retry streak. Retry totals remain cumulative for the
process. A database sampling error logs only `backlog_unavailable` and its error class, leaves
delivery behavior unchanged and retries at the next interval. Guard loss emits `guard_lost` and
stops publication through the existing lifecycle. Fatal/invalid-event classes remain in
`worker_stopped`. Logs contain no raw connection errors, credentials or event envelopes.

These signals are structured log fields with reviewable development thresholds. No Prometheus
endpoint, dashboard, paging integration, persistence or monitoring service is added. Operators
must collect the logs and define actual alert routing/SLOs separately. Backlog count queries can
cost more as retained state grows; deadlines bound sampling but do not establish production scale.

## Recovery and repair

1. Check topic configuration with `--check` before enabling publication. A mismatch requires a
   reviewed migration; do not recreate the topic or increase partitions to make the tool green.
2. On broker outage or repeated retries, keep the pending rows. HTTP writes remain independent.
   Check broker availability and configuration; a growing age is evidence of delayed publication.
3. On `guard_lost`, fatal invalid-event errors or exit 2, stop and confirm the old worker process
   is gone before replacement. Inspect sanitized error classes and retained row IDs privately.
   Do not mark unacknowledged events published, rewrite IDs or delete poison records as recovery.
4. Restarting the relay retries the unchanged pending head. A broker ACK followed by a lost DB
   mark can replay a duplicate. Consumers need their own durable deduplication/version handling.
5. Normal consumer restart resumes valid committed offsets. Offset reset/replay is a separate
   operator action after stopping the affected consumer and assessing durable state, retention
   and duplicate side effects. This tool provides no reset command and no live group manipulation.
6. If retention has removed required history, ordinary restart cannot restore it. Preserve the
   incident and propose a reviewed recovery/backfill. Outbox retention and application record
   deletion remain unchanged. Never claim seven-day retention supplies a complete restore plan.

Rollback consists of stopping the optional worker. Durable pending state remains; do not remove
Compose volumes. Tests use temporary databases/topics/groups and do not enable the application
Outbox profile or create `orders.events.v1`.

Still required for full SCRUM-18: actual durable-consumer integration, production topology, ACLs,
retention/restore policy and monitoring ownership. These remain dependencies and owner/operator
decisions. Do not mark the whole ticket complete on the strength of probe acceptance.

Source checked 2026-11-03: [Apache Kafka 4.4 basic operations](https://kafka.apache.org/44/operations/basic-kafka-operations/)
for explicit topic creation, configuration and partition migration implications;
[aiokafka consumer guide](https://aiokafka.readthedocs.io/en/stable/consumer.html) for manual offsets,
group isolation and restart behavior. The running Kafka 4.4 CLI was verified on disposable topics.
