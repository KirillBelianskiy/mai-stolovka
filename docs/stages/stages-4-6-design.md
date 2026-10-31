# Stages 4–6 design integration — SCRUM-12

Status: active design coordination, 2026-10-31. Runtime implementation, infrastructure changes,
merges and deployment are not authorized by these design tasks. Product baseline: 4fb6886.
This is the coordinator-owned integration register; individual owners keep their exclusive documents.

## Deliverables and owners

| Task | Owner / exclusive file | Published design / current evidence |
| --- | --- | --- |
| SCRUM-13 Outbox | kirill_bel; docs/architecture/event-publication.md | [PR #2](https://github.com/KirillBelianskiy/mai-stolovka/pull/2), head 7adf583; [green CI](https://github.com/KirillBelianskiy/mai-stolovka/actions/runs/41200871126) |
| SCRUM-14 Notification | bobr2610; docs/architecture/notification-delivery.md | Setup/producer READBACK 10021, preview 10028 and safety READBACK [10032](https://belianskiykirill-1793393094981.atlassian.net/browse/SCRUM-14?focusedCommentId=10032); design PR not yet observed |
| SCRUM-15 WebSocket | kirill_bel; docs/architecture/websocket-delivery.md | [PR #3](https://github.com/KirillBelianskiy/mai-stolovka/pull/3), head 095d51e; [green CI](https://github.com/KirillBelianskiy/mai-stolovka/actions/runs/41203370408) |
| SCRUM-16 Frontends | bobr2610; docs/architecture/frontend-integration.md | Assigned separately; branch-start ACK and design PR not yet observed |

These review documents live on separate branches from main. A missing local file on one branch
is not a missing assignment or permission to recreate another owner's work. Review the linked PRs
at their actual heads. Update this evidence register after new handoffs; do not present the table
as an automatically refreshed dashboard. The generated skill v0006 and launch brief are in
[skill PR #4](https://github.com/Bobr2610/mai-food-codex-skill/pull/4), stacked on earlier reviews.

## Agreement and approval states

Use four distinct states: proposed, peer-readback, owner-approved, implemented-and-verified.
A PR, green CI, Jira ACK or peer READBACK is not owner approval or proof of implemented behavior.
Existing Stage 3 contracts are implemented; all new interfaces/operational choices below remain
proposals until explicitly approved. No new public API or JSON Schema is committed by this register.

| Boundary / decision | Existing fact or proposal | State / next review |
| --- | --- | --- |
| Order events | Existing closed v1 envelope with stable event_id, aggregate_id and payload order_version | Implemented Stage 3; preserve unless separately versioned |
| Producer → Notification | Order UUID key; unchanged v1; at-least-once duplicates/late versions; durable consumer responsibility before offset commit | Peer-readback in SCRUM-14 comment 10021; consumer design details and owner gates pending |
| Relay availability | Proposed single worker, PG session advisory guard, no broker I/O in business transactions, pending-event retry before intentional later-version progression | SCRUM-13 proposal; owner must accept availability/poison/deadline tradeoffs |
| Topic durability/replay | Proposed orders.events.v1, seven-day delete retention, separate groups; production partitions/replication/ACLs not approved | Owner operations decision; reconcile with Notification recovery window |
| Notification durable state | Existing service has no DB adapter; persistent inbox/retries/dedup are required before offset commits | SCRUM-14 preview 10028 recommends a service-owned PostgreSQL inbox/delivery store over Kafka state/retry topics; owner approval still required |
| User → Notification recipient | Existing User /me is own-user Bearer API, not a machine lookup by event user_id | New narrowly authorized service interface/permission state must be proposed and reviewed; no direct DB reads or borrowed client JWT |
| Notification freshness | Duplicate/late/gap handling and READY followed by COMPLETED before dispatch | Preview 10028 proposes monotonic watermark and stale READY suppression; safety boundary acknowledged in 10032, owner decision pending |
| Bot → permission state | Existing verified Telegram identity does not establish a durable message-permission lifecycle | SCRUM-14 proposes trusted evidence, ownership, blocked/revoked behavior and recovery |
| Kafka → kitchen | Independent kitchen group; manual contiguous commits, valid-offset resume and proposed latest reset only without a valid position; partition assignment before readiness | SCRUM-15 singleton proposal; replicas require fan-out/offset policy review |
| Browser → kitchen WebSocket | Proposed exact-origin check, first-frame staff JWT, bounded pre-auth transport, expiry close; no token in URL | SCRUM-15; SCRUM-16 READBACK plus owner approval required |
| Kitchen WebSocket → UI | Proposed ready queued before broadcast visibility with one socket writer, minimal orders.changed hints, bounded queues and subscribe-before-REST recovery | SCRUM-15/16 must reconcile exact messages/limits before schema publication |
| Browser state/credentials | Static exports and existing access-token APIs; no refresh/session endpoint exists | SCRUM-16 proposes storage/expiry UX and separation of Query server state vs local cart; owner gates for new auth contracts |
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
These are agreed design constraints; the actual consumer document and implementation remain
unverified until the corresponding PR and later runtime acceptance checks exist.

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
| SCRUM-19 | WebSocket authentication and bounded hub | SCRUM-15 approved and SCRUM-16 READBACK; origin/JWT/role/expiry/frame/queue isolation tests |
| SCRUM-20 | Kafka hints and REST reconciliation integration | Approved SCRUM-13/15/16 contracts; duplicate/gap/fetch-race/restart/filtered-membership tests |

Notification and frontend implementation units are to be proposed by their design owner with
measurable tests and explicit dependencies. The coordinator consolidates those tickets after the
actual handoff, preserving author ownership. No database, permission API, browser session or
production topology is selected merely to make a backlog ticket appear ready.

After both Stage 4 designs receive peer READBACK, collect the owner's unresolved decisions and
mark their disposition in Jira. Do the same for the Stage 5/6 pair. Then split approved execution
into service-owned tickets/PRs; do not merge design approval and runtime acceptance into one status.

## Review and delivery acceptance

- All four documents have independent Jira-owned branches/PRs with exclusive file diffs, sources,
  alternatives, recommendations, owner gates and future acceptance tests.
- Counterpart ACKs and READBACKs cite specific comment IDs/PR commits. Startup/setup is reported
  evidence, not proof of continuous remote execution or correctness of private files.
- Shared interface additions are reviewed by both affected owners before the coordinator updates
  packages/contracts/OpenAPI. No committed wire change is needed just to publish a design draft.
- Product CI is green at the actual heads; docs-only CI does not prove future runtime scenarios.
- Each HANDOFF links its PR, SHA, changed paths, actual checks and outstanding approvals.
- No PR is merged, no runtime feature is started and no production deployment is claimed here.
