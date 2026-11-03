# SCRUM-18 — development topic operations

Status: first implementation slice, 2026-11-03. The owner requested continuing the recorded
backlog order. This branch is stacked on SCRUM-17 head `35915fa`; it does not merge that PR.
Full SCRUM-18 acceptance remains incomplete.

## Backlog and skill reconciliation

GitHub issues #9 and #10 are coordination channels, not the implementation backlog. Issue #9
contains a connectivity seed. The Windows readback in issue #10 reports consistent designs
and green SCRUM-17 checks; it does not establish a new execution agreement or Mac ACK.

[Design integration PR #4](https://github.com/KirillBelianskiy/mai-stolovka/pull/4), head `5ffed86`,
records the suggested order: SCRUM-22 and 17/18, then 23/24, then 19/20. Frontend foundations
25/27 can proceed against existing APIs, followed by 26/28. SCRUM-17 is implemented in
[PR #8](https://github.com/KirillBelianskiy/mai-stolovka/pull/8). SCRUM-18's local operations slice
can start independently of new recipient credentials or Notification storage; consumer durability
and production operations remain dependencies of the full ticket.

The installed `mai-food-codex-skill` v0008 records SCRUM-17 as its bounded assignment.
The current continuation request authorizes starting subsequent work; it does not settle every
D1–D10 policy. Retain its service boundaries, test-first workflow and no-merge/deployment rules.
The local mailbox skill concerns read-only agent dialogue, not application implementation.
The generic Forge skill is a generator and needs no modification for this work.

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
- Green: nine focused test methods pass, including eight drift subcases and three malformed
  metadata subcases. Docker interactions are simulated; these do not prove actual Kafka CLI
  output compatibility or live provisioning.
- All 15 root contract/operations tests pass. Root Ruff checks (including W), formatting and
  `git diff --check` pass. The new tests run in the existing contracts CI job's
  discovery command without additional CI configuration.
- Docker was unavailable: `docker compose ps --format json` could not connect to the daemon.
  The real `--check` invocation also exited 1 with a sanitized failure. Default plan mode succeeded
  without Docker. No live topic was created or modified and no pending orders were published.

Still required for SCRUM-18: live Kafka 4.4 CLI verification, isolated topic tests for independent
consumer groups and exact envelopes, backlog/age/ACK/retry/guard diagnostics, recovery/repair
runbook and consumer durability integration. Production topology, ACLs and recovery policy remain
owner/operator decisions. Do not mark the whole ticket complete on the strength of this slice.

Source checked 2026-11-03: [Apache Kafka 4.4 basic operations](https://kafka.apache.org/44/operations/basic-kafka-operations/)
for explicit topic creation, configuration and partition migration implications. Exact running-image
CLI compatibility remains unverified while Docker is stopped.
