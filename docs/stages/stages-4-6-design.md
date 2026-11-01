# Stages 4–6 design integration — SCRUM-12

Status: sequential design handoff for owner review, 2026-11-01. Runtime implementation, infrastructure changes,
merges and deployment are not authorized by these design tasks. Product baseline: 4fb6886.
This is the coordinator-owned integration register. The owner ended Misha's participation and
transferred SCRUM-14/16 to kirill_bel on 2026-11-01. All four designs now have one delivery owner;
this handoff does not claim independent peer review of the completed Notification/frontend drafts.

## Deliverables and owners

| Task | Owner / exclusive file | Published design / current evidence |
| --- | --- | --- |
| SCRUM-13 Outbox | kirill_bel; docs/architecture/event-publication.md | [PR #2](https://github.com/KirillBelianskiy/mai-stolovka/pull/2), head 7adf583; [green CI](https://github.com/KirillBelianskiy/mai-stolovka/actions/runs/41200871126) |
| SCRUM-14 Notification | kirill_bel; docs/architecture/notification-delivery.md | [PR #6](https://github.com/KirillBelianskiy/mai-stolovka/pull/6), head a790b26; [green CI](https://github.com/KirillBelianskiy/mai-stolovka/actions/runs/41324733014); historical Misha preview/READBACK preserved |
| SCRUM-15 WebSocket | kirill_bel; docs/architecture/websocket-delivery.md | [PR #3](https://github.com/KirillBelianskiy/mai-stolovka/pull/3), head 095d51e; [green CI](https://github.com/KirillBelianskiy/mai-stolovka/actions/runs/41203370408) |
| SCRUM-16 Frontends | kirill_bel; docs/architecture/frontend-integration.md | [PR #7](https://github.com/KirillBelianskiy/mai-stolovka/pull/7), head f93d522; [green CI](https://github.com/KirillBelianskiy/mai-stolovka/actions/runs/41325093132); sole-author reconciliation of WS head 095d51e |

These review documents live on separate branches from main. A missing local file on one branch
is not a missing assignment or permission to recreate another owner's work. Review the linked PRs
at their actual heads. Update this evidence register after new handoffs; do not present the table
as an automatically refreshed dashboard. Active skill v0007 is in
[skill PR #5](https://github.com/Bobr2610/mai-food-codex-skill/pull/5), stacked on the historical
[v0006 collaboration review](https://github.com/Bobr2610/mai-food-codex-skill/pull/4). Earlier versions
and Misha's Jira comments remain historical evidence, not a required future ACK.

## Agreement and approval states

Distinguish proposed, self-reconciled, independent peer-readback, owner-approved and implemented-and-verified.
A PR, green CI, Jira ACK or peer READBACK is not owner approval or proof of implemented behavior.
Existing Stage 3 contracts are implemented; all new interfaces/operational choices below remain
proposals until explicitly approved. No new public API or JSON Schema is committed by this register.

| Boundary / decision | Existing fact or proposal | State / next review |
| --- | --- | --- |
| Order events | Existing closed v1 envelope with stable event_id, aggregate_id and payload order_version | Implemented Stage 3; preserve unless separately versioned |
| Producer → Notification | Order UUID key; unchanged v1; at-least-once duplicates/late versions; durable consumer responsibility before offset commit | Historical peer-readback 10021; completed PR #6 self-reconciles durable responsibility, contiguous offsets and recovery; owner gates pending |
| Relay availability | Proposed single worker, PG session advisory guard, no broker I/O in business transactions, pending-event retry before intentional later-version progression | SCRUM-13 proposal; owner must accept availability/poison/deadline tradeoffs |
| Topic durability/replay | Proposed orders.events.v1, seven-day delete retention, separate groups; production partitions/replication/ACLs not approved | Owner operations decision; Notification proposes earliest for new groups and expired-offset review, unlike ephemeral Kitchen latest reset |
| Notification durable state | Existing service has no DB adapter; persistent inbox/retries/dedup are required before offset commits | PR #6 recommends notifications_db inbox/delivery store, local atomic state and durable quarantine; new logical DB/retention/backup approval required |
| User → Notification recipient | Existing User /me is own-user Bearer API, not a machine lookup by event user_id | PR #6 proposes scoped recipient lookup and authenticated observation intake; exact API/service-principal contract still needs owner review; no borrowed JWT/direct DB reads |
| Notification freshness | Duplicate/late/gap handling and READY followed by COMPLETED before dispatch | PR #6 specifies per-version conflicts and last local eligibility check, no recall/unseen-state guarantee; timeout duplicates and retry window need owner decision |
| Bot → permission state | Existing verified Telegram identity does not establish a durable message-permission lifecycle | SCRUM-14 proposes trusted evidence, ownership, blocked/revoked behavior and recovery |
| Kafka → kitchen | Independent kitchen group; manual contiguous commits, valid-offset resume and proposed latest reset only without a valid position; partition assignment before readiness | SCRUM-15 singleton proposal; replicas require fan-out/offset policy review |
| Browser → kitchen WebSocket | Proposed exact-origin check, first-frame staff JWT, bounded pre-auth transport, expiry close; no token in URL | PR #7 self-reconciles current SCRUM-15 first-frame auth, expiry and close behavior; owner approval remains required |
| Kitchen WebSocket → UI | Proposed ready queued before broadcast visibility with one socket writer, minimal orders.changed hints, bounded queues and subscribe-before-REST recovery | PR #7 matches head 095d51e; dirty generations, filtered membership and REST fallback specified; wire/limits approval precedes schema publication |
| Browser state/credentials | Static exports and existing access-token APIs; no refresh/session endpoint exists | PR #7 recommends memory-only credentials, explicit re-login and account-scoped sessionStorage intent journal; persistence/privacy UX needs approval |
| Changed total / uncertain POST | Existing expected_total_amount conflict and UUID-key original-response replay | SCRUM-16 uses existing semantics; no automatic acceptance of changed price or duplicate new intent |

## Cross-design consistency checks

Producer and Notification review must agree on the point durable responsibility is acquired.
The expected boundary is a persisted inbox/retry obligation before offset commit; sending to
Telegram is not an atomic part of Kafka or PostgreSQL. Replayed offsets must not create another
logical obligation for the same event. Same event_id with incompatible contents is a conflict,
not a harmless duplicate. A later order_version is not proof that every earlier event was seen.
The consumer must state how its selected storage recovers and how retry/retention affect that.

Counterpart safety READBACK 10032 accepted sequential processing per partition (or a contiguous
durable prefix), topic/partition/offset diagnostics, durable quarantine before offset advancement,
and atomic watermark/pending-delivery updates. It also accepted the last eligibility-check boundary,
claim/lease-expiry treatment and the limits of unconsumed terminal events and network-send races.
PR #6 now includes these design constraints, per-version conflict detection and explicit replay/
restore boundaries. Its document is self-reconciled against producer head 7adf583; runtime scenarios
remain unimplemented/unexecuted. Historical peer agreement is not approval of every later detail.

The approved lifecycle allows READY -> COMPLETED, not READY -> CANCELLED. Cancellation is
limited to PENDING/PREPARING under the confirmed role/cutoff policy. A READY/CANCELLED branch
conflict for the same order is inconsistent history or a future-policy proposal, not permission to
add a transition. Same aggregate/version with incompatible state must be diagnosed as a conflict;
late copies must not resurrect a terminal order.

Before recommending stale READY suppression, identify how current order state is obtained. Existing
Order REST accepts end-user/staff JWT roles; an event contains no authority to call it. A consumer
may not impersonate ADMIN or directly read orders_db. Either propose an appropriately scoped
service lookup, explain a bounded local-version policy and its limitations, or leave suppression
as an unresolved owner decision. Do not present a perfect freshness guarantee across independent
Order/Telegram calls: state can change after a last check and before an external send.

Recipient/permission design must distinguish Telegram identity, evidence of write permission,
operational send eligibility and later blocked/revoked state. A browser callback alone is not
server authorization. The current User login projection has no durable permission model. Select
which service owns verified permission observations and how updates arrive through an authenticated
interface; do not silently add fields to the public login/profile/event contracts. Client-owned
profile access is not a Notification service principal. Any future service token must have explicit
issuer/audience/role or scope restrictions; reuse of the current staff role is not preapproved.

WebSocket and frontend review must agree on pre-auth limits, role matrix, token expiration/re-login,
wire version, backpressure closes, the distinction between connection_id and replay cursor, and
recovery after lost hints. A client must retain invalidations arriving during REST fetch and must
reconcile filtered-list membership, not only mutate cached records. Current list pagination is not
a global snapshot, and a hint does not authorize a mutation. Cancellation/status requests continue
using expected_version; unknown POST outcomes reuse their original key/body before a new intent.

## Implementation backlog and dependency gates

The following are future implementation tasks, not permission to start them during this design phase:

| Jira | Implementation unit | Design dependencies / acceptance focus |
| --- | --- | --- |
| SCRUM-17 | Outbox worker lifecycle/publication | SCRUM-13 approved and SCRUM-14 boundary reconciled; crash/ACK/mark/guard/version tests with PG+Kafka |
| SCRUM-18 | Topic operations and consumer integration | Approved retention/topology/ACLs and consumer durability; outage/backlog/group/schema/monitoring tests |
| SCRUM-19 | WebSocket authentication and bounded hub | SCRUM-15/16 proposals approved; origin/JWT/role/expiry/frame/queue isolation tests |
| SCRUM-20 | Kafka hints and REST reconciliation integration | Approved SCRUM-13/15/16 contracts; duplicate/gap/fetch-race/restart/filtered-membership tests |
| SCRUM-22 | User recipient/permission contract | Approve User-owned evidence precedence, narrow service authority and exact API before implementation; N8/N10 |
| SCRUM-23 | Notification inbox/observations/offsets | Approve separate logical DB, retention and poison policy; real PG/Kafka N1–N5/N9 |
| SCRUM-24 | Telegram dispatch/retries/update receipt | SCRUM-22/23 plus approved ambiguity, budgets and intake mode; N5–N9 with fake Bot API faults |
| SCRUM-25 | Mini App auth/menu/cart/profile | Approved credential UX; existing APIs and static pages; F1–F4/F12 |
| SCRUM-26 | Mini App checkout/history | SCRUM-25 and approved intent journal/clear policy; F4–F8 |
| SCRUM-27 | Kitchen auth/REST queue/roles | Existing REST contracts and approved credential UX; F1–F3/F8; WS connector remains SCRUM-20 |
| SCRUM-28 | Kitchen ADMIN menu/slots | SCRUM-27, existing admin APIs; F11 and denied non-ADMIN tests |

N/F IDs refer to the corresponding proposed Notification/frontend PR's acceptance tables, not
executed tests. Native Jira Blocks links gate the new tasks: SCRUM-14 -> 22/23/24, SCRUM-22/23 ->
24, SCRUM-16 -> 25/26/27/28, SCRUM-25 -> 26, SCRUM-27 -> 28/20. Existing 13/14 -> 17/18 and
15/16 -> 19, 13/15/16 -> 20 links remain. Tickets stay Todo/unassigned until approvals/execution
assignment; their existence is not permission to implement. No database, service credential or
browser session is approved merely to make a ticket appear ready.

## Review and delivery acceptance

- All four documents have independent Jira-owned branches/PRs with exclusive file diffs, sources,
  alternatives, recommendations, owner gates and future acceptance tests.
- Historical counterpart ACKs/READBACKs remain attributed; the owner-authorized sequential takeover
  removes future departed-agent waiting. New sole-author reconciliation is not independent peer review.
- Shared interface additions need explicit contract/owner review before packages/contracts/OpenAPI
  changes. No wire/schema/API edit is needed to deliver these design documents.
- Product CI is green at the actual heads; docs-only CI does not prove future runtime scenarios.
- Each HANDOFF links its PR, SHA, changed paths, actual checks and outstanding approvals.
- No PR is merged, no runtime feature is started and no production deployment is claimed here.
## Consolidated owner decision register

All entries below are proposed, not approved by the ownership change. Existing Stage 3 business
policies remain confirmed. Choose these before the dependent implementation ticket starts:

| ID | Recommendation / alternative | Blocks |
| --- | --- | --- |
| D1 Relay availability | One monitored PG-guarded relay, halt retained poison rows and bound ambiguous send shutdown; accept temporary head-of-line delay or commission another design | SCRUM-17 |
| D2 Broker/replay operations | Approve dev topic explicitly; production replicas/minISR/ACLs, retention and restore window need an operator. Seven-day retention is a proposal, not established recovery coverage | SCRUM-18/23 |
| D3 Notification durable store | notifications_db with independent owner/backups; alternative Kafka materialization/retry topics is more operational work | SCRUM-23 |
| D4 Identity/permission | User-owned verified evidence, scoped recipient lookup and deduplicated observation input; exact API, machine credentials and regrant precedence need review | SCRUM-22/24 |
| D5 Notification dispatch | Local known-state suppression, no perfect freshness/recall; proposed 8 attempts/24h from occurred_at, 10s call/60s lease and bounded ambiguous retries vs operator-only ambiguity repair | SCRUM-24 |
| D6 Bot intake/message | Choose trusted webhook or long polling, update receipt/recovery, initial readiness text/link and grant-after-delay behavior | SCRUM-22/24/25 |
| D7 WebSocket | First-frame staff JWT, exact Origin, ready/minimal hints, 5s/12KiB/128 bounds and close conventions; tickets/cookies remain alternatives | SCRUM-19/20 |
| D8 Browser credentials | Memory JWT and explicit re-login; durable sessions require a separate backend design. Approve expiry/reopen UX | SCRUM-25/27 |
| D9 Checkout recovery | Account-bound validated sessionStorage journal, same key/body and clear-loss warning vs memory-only recovery; approve storage/privacy/forced-logout limitations | SCRUM-26 |
| D10 Freshness/display | Proposed visible 30s REST recovery plus focus/online; accept eventual non-atomic pagination and explicit timezone display | SCRUM-20/26/27/28 |

## Sequential handoff and proposed execution order

Finish document/API/schema validation and green CI, then leave SCRUM-12/14/16 In Review. Owner
review and implementation authorization are the next boundary, not another Misha ACK. Suggested
future order after decisions: SCRUM-22 and 17/18, then 23/24, then 19/20; frontend foundations
25/27 can proceed against existing APIs when their own decisions are approved, followed by 26/28.
Each future task needs an explicit implementation assignment and focused PR. No merge/deployment
is performed by this design handoff. Ruff quality-gate [PR #5](https://github.com/KirillBelianskiy/mai-stolovka/pull/5)
is separately green and remains unmerged.
