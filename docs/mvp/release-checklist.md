# MAI Food Mac MVP release evidence — #29

Status: preparation. Candidate SHA, review, rollout approval and cutover date are pending.

## Candidate manifest

The coordinator fills this in for the exact reviewed candidate. Attach immutable evidence links.

| Input | Required record |
| --- | --- |
| Source | Candidate SHA, base, ordered workstream PRs and exact heads, reviews, exact-head CI and any post-CI change |
| User | Session/login contract and migrations, recipient eligibility and block/unblock behavior, test account provisioning |
| Kitchen | Staff login and role matrix, authenticated WebSocket and REST reconciliation contract, mobile/tablet and external route evidence |
| Notification | Outbox topic/group and durability settings, Notification migration and worker identity, READY policy, Telegram ambiguity and retry/recovery rules |
| Mac Infra | Image IDs/digests, migration heads, TLS/routing, Mac runtime and operator access, identities of backup/restore targets and rollback artifacts, approved staging access and runbook |
| Acceptance | Local harness report with build identity, candidate A1–A8 outcomes, remote and network-switch checks, restore/cutover evidence, unresolved defect list |

## Cutover and rollback rehearsal

Use the Mac Infra procedure against disposable synthetic state. Record each command or approved
operator action with UTC timestamp, result and operator. Link the source and target manifest
rather than including private addresses, credentials or webhook secrets.

1. Pin the prior working route/configuration, images, schema and worker positions. Confirm tested
   compatibility of the prior release with the proposed schema and data. Review the approved
   restore path if compatibility requires recovery instead of reusing the migrated database.
2. Record a pre-cutover synthetic pending order, a completed history entry, an unresolved READY
   obligation and wallet/ledger/capacity totals. Take the reviewed backup and record the checksum.
3. Perform the isolated candidate cutover. From outside the Mac's LAN verify public customer launch,
   staff login, authenticated WebSocket, REST and controlled READY delivery on the candidate.
4. Trigger the approved rollback in rehearsal and observe routing return to the pinned prior
   release. Verify the previous app/API identities, staff access, protected routes and pending
   work recovery. Reconcile the order/key, wallet, slot, Outbox, inbox and consumer positions.
   Check that one worker set owns dispatch and that pending work is neither lost nor double claimed.
5. Record traffic interruption and measured recovery/loss against approved thresholds. Document
   any data produced during the cutover that needed reconciliation and show that customer history
   and funds reconcile. If an invariant fails or restore exceeds approved limits, mark rehearsal
   failed and require a corrected rehearsal.

Pass requires reviewed merge/rollout order, matching exact-head CI and A1–A8 evidence, all
required operational rehearsals, disposition of blockers and recorded owner approval. Record
authorized rollout separately with actual customer, staff, API, WebSocket and bot results.
