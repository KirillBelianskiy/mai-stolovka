# MAI Food pilot readiness runbook

Status: preparation draft; not an authorization to run a pilot, change production, or send Telegram messages.

This runbook distinguishes repository/local evidence from operational acceptance. A green CI run or a local Compose stack does not establish production routing, backup coverage, alert delivery, or recovery readiness.

## Current readiness and evidence boundary

As of 2026-11-04, implementation is distributed across open pull requests with separate review and integration gates. The relevant work is not yet an integrated release candidate. The following evidence exists, but does not by itself establish pilot readiness:

- Outbox design and runtime work are under review in PRs #11, #12 and #31. SCRUM-18 still distinguishes local structured logs from production paging, disk monitoring, alert routing, and approved operations.
- Notification's durable inbox is implemented in PR #43 at `e10599381941b181b928ab8fdcc8f4fac17467d3`, stacked on PR #12. Its repository CI, including isolated PostgreSQL/Kafka integration, passed. It remains unmerged and awaits independent integration/review. This is not evidence of production restore or live consumer operations.
- User persistent sessions are in PR #42 at `4c2e77f30d93f4294d63a109607a11b14a892643`; recipient permissions are in PR #46 at `36a689709771cfc1938171e663e4a08d74dfa43f`. Their backend and isolated integration checks pass. The independent Cloudflare Pages check fails and is tracked under #25; its root cause is not established here.
- Kitchen queue and admin UI are in PRs #38 and #39, dependent on the review chain shown on GitHub. Their local frontend typecheck/build evidence does not establish full production service integration.
- Hosting assessment PR #35 records public DNS/route observations and repository deployment assumptions. Cloudflare dashboard logs and the actual backend/PostgreSQL/Kafka runtime host have not been verified. Do not infer a service host from a website HTTPS response.

Therefore this draft cannot claim an exercised integrated backup/restore, production secrets inventory, monitored Kafka recovery, measured pilot capacity, rollback readiness, or on-call ownership.

## Decision register required before pilot

Record the approving owner, decision, date, and evidence link for each item. Do not replace a blank with an assumed default.

| Decision | Current state | Required evidence |
| --- | --- | --- |
| Pilot owner and named primary/backup operators | Unresolved | Names, contact route, coverage window, and access verification |
| Pilot scope and participant approval | Unresolved | Approved cohort, dates, support route, and explicit rollout approval |
| RPO and RTO per database/service | Unresolved | Owner-approved targets and measured restore results |
| Retention for orders, sessions, Notification obligations, logs, and Kafka | Unresolved | Owner-approved durations, deletion behavior, and restore implications |
| Alert destinations and escalation | Unresolved | Test notification evidence and named responder |
| Kafka durability, retention, replication, and disk thresholds | Unresolved | Approved production topology/configuration and capacity evidence |
| Secret inventory, custodians, and rotation schedule | Unresolved | Secret names/locations/owners only; never record secret values |
| Backend, PostgreSQL, Kafka and bot runtime locations | Unverified | Authorized host/provider evidence and route validation |
| Pilot load budget and rollback triggers | Unresolved | Measured capacity, threshold values, decision owner, and rollback proof |

## Pre-exercise gate

Do not perform backup/restore or pilot acceptance until all applicable checks are evidenced:

1. A single release candidate pins reviewed application and infrastructure heads, migration versions, container images, and configuration references. Confirm the target environment is isolated and disposable.
2. The operator confirms the tested database endpoints are not production and that the restore target contains no real customer data. Record the exact sanitized environment identity.
3. The owner approves RPO/RTO, retention, alert routing, Kafka topology, pilot load budget, rollback triggers, named operators, and participant/rollout scope.
4. The secret custodian verifies required credentials are present and least-privileged. Record names and rotation/expiry metadata only, never values.
5. The team verifies API and WebSocket routes, TLS/origin rules, health/readiness signals, bot webhook intake, and monitoring from the intended isolated environment. A static HTTPS 200 is not sufficient.
6. An operator is available to stop the exercise if data isolation, migration, backup integrity, or alerting checks fail.

Record pass/fail, timestamp, operator, candidate SHA, environment label, and artifact links for each step. Until this evidence exists, mark the exercise BLOCKED rather than PASS.

## Backup and restore exercise (blocked pending integrated candidate and approval)

When authorized, use disposable synthetic state only and record the exact commands and tool/image versions in the execution record.

1. Create synthetic users, menu rows, slots, orders, idempotency keys, Outbox events, Notification obligations/errors, and Kafka offsets representative of the selected acceptance cases.
2. Capture a consistent backup using the approved production-equivalent procedure. Record start/end times, size, checksum, database/schema versions, and whether Kafka state/configuration is included or reconciled separately.
3. Restore into a fresh isolated target. Never overwrite the source environment.
4. Apply only the approved migration/reconciliation procedure. Verify row counts and invariants: orders and idempotency outcomes agree; Outbox events remain publishable or already acknowledged; durable Notification obligations are present; Kafka committed offsets do not skip undurable responsibility.
5. Exercise consumer restart, duplicate replay, and the documented offset-expiry/reconciliation path. Confirm poison records remain inspectable and do not silently advance beyond durable responsibility.
6. Measure recovery time and data loss against the approved RTO/RPO. Capture query outputs with personal data redacted.
7. Verify application readiness and operator alerts against the restored target. Record failures, corrective action, and a fresh run; do not convert an untested step into a pass.

Current result: NOT RUN. No integrated release candidate, approved targets, or authorized recovery exercise is evidenced in this checkout.

## Outage and escalation cards

Use only after the integrated candidate defines the actual dashboards, commands, endpoints, and operator access. Fill in and review these placeholders before pilot:

| Signal | Immediate response | Escalation / recovery gate |
| --- | --- | --- |
| API or WebSocket readiness lost | Confirm scope and recent candidate/config changes; stop new pilot activity if customer actions cannot be reconciled | Named primary operator; restore traffic only after health, auth, and REST reconciliation pass |
| Kafka consumer lag or ACK/mark guard failure | Preserve evidence; do not manually advance offsets or publish pending orders | Follow approved Outbox/Notification recovery procedure; resume after durable state and offsets reconcile |
| Poison/quarantined event | Preserve payload reference and error metadata; do not delete or repeatedly retry blindly | Escalate to service owner; use reviewed repair/replay procedure |
| Telegram send timeout or ambiguous result | Treat delivery as unknown; do not claim exactly-once delivery or blindly resend | Follow approved bounded retry/duplicate-message policy and verify recipient eligibility |
| Database disk/capacity threshold | Stop optional load generation; preserve database and logs | Escalate at owner-approved thresholds; do not delete retention data outside the approved policy |
| Restore or migration mismatch | Stop rollout and isolate the target | Preserve backup; engage database/service owner; require a successful repeat exercise |

Exact thresholds, dashboards, contacts, commands, and paging destinations are intentionally blank pending owner approval and verified hosting/runtime access.

## Rollback and closeout

Rollback procedure, responsible operator, data compatibility rules, and decision threshold remain unresolved. Before pilot, document a tested rollback that addresses both application artifacts and irreversible schema/data changes; restoring an old binary alone may not be safe.

After an authorized exercise, attach the candidate SHA, environment label, sanitized command transcript, backup checksum, measured RPO/RTO, alert delivery evidence, observed gaps, and owner sign-off. Keep this runbook marked BLOCKED until the required checks have actually passed.
