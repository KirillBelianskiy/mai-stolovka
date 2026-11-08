# Durable notification delivery — SCRUM-14

Status: design proposal for owner review, 2026-11-01. No worker, database, migration, bot,
consumer or new API is implemented here. Product baseline: `4fb6886`. Owner: `kirill_bel`, after
owner-authorized takeover from `bobr2610`. Preserve Misha's Jira preview 10028 and READBACKs
10032/10038; this completed document has sole-author reconciliation, not independent peer review.

Producer reference: [Outbox design PR #2](https://github.com/KirillBelianskiy/mai-stolovka/pull/2),
head `7adf583`. The existing [v1 envelope](../../packages/contracts/events/envelope-v1.schema.json)
and [order lifecycle](order-lifecycle.md) remain unchanged.

## Decision and alternatives

Recommend a Notification-owned `notifications_db` logical PostgreSQL database on the existing
PostgreSQL instance, with its own non-superuser owner, migrations and backups. This is an explicit
exception proposal to the initial no-relational-DB shell, requiring owner approval before changes.
Notification owns delivery responsibility, retries and operational suppression; User owns identity
and verified permission observations. No cross-database reads, foreign keys or shared ORM imports.

| Option | Benefit | Cost / decision |
| --- | --- | --- |
| Service-owned PostgreSQL inbox and scheduler | Local atomic deduplication, watermark and delivery scheduling; existing database technology | Additional logical DB and backup/retention obligations; recommended, not approved |
| Kafka state/retry topics with durable local state | Avoids another relational DB | Requires explicit materialization, recovery, delayed scheduling and offset/state coordination; more complexity for this team |
| Persistent local file / SQLite | Small local footprint | Single-host ownership and recovery complicate failover/replicas; not the shared runtime recommendation |
| In-memory set or aiogram MemoryStorage | Simple prototype | Restart loses retry/dedup state; does not satisfy durable responsibility |

Using aiogram does not supply an application inbox or durable delivery scheduler. No Redis,
Kubernetes, distributed locks or external scheduler is proposed. Start with one consumer and one
bounded dispatcher; future parallel dispatch still uses the local database claim rules below.

## Producer and consumer boundary

Use proposed topic `orders.events.v1`, order UUID keys and independent group
`notification-orders-v1`. Never use the Kitchen group. Every published event retains its original
`event_id`, `event_version`, `occurred_at`, aggregate ID and payload; a resend is not a new event.
At-least-once delivery, delayed duplicates and late lower aggregate versions are normal.

The v1 payload contains a product user UUID, not a Telegram recipient. It contains no bot token,
permission grant, item names, slot times or authority to call other services. Only a valid
`ORDER_STATUS_UPDATED` with `status=READY` proposes a user notification; other valid events still
receive a durable processed/no-send outcome and update known order state. Do not invent additional
customer notifications or obtain missing data through direct database reads. Initial message can
use the stored order number and readiness status; links/content need owner review.

## Proposed persistent records and atomic ingestion

These are conceptual records, not committed schema definitions:

- Inbox: unique event ID, validated canonical-content hash, aggregate/version, event type, source
  topic/partition/offset, receipt time and durable outcome. Reject duplicate JSON keys before
  canonicalization; object key order alone must not create a content conflict.
- Order observation: order ID, immutable identity fields, highest accepted version/status and
  substantive fingerprints indexed by order/version. Keep enough per-version fingerprints to
  detect contradictory older copies; a highest-version watermark alone is insufficient. Compare
  event type and payload fields for substantive identity, excluding event ID and emission time.
- Delivery: unique logical purpose `(order_id, READY, order_version)`, originating event ID,
  user UUID, state, attempts, next attempt time, claim token/expiry, last sanitized error,
  permission revision used, Telegram message ID after acknowledged success and ambiguity flag.
- Quarantine: source location and bounded protected diagnostic content/hash, conflict reason,
  review state and operator disposition. Oversize/unparseable events use source location/hash
  without pretending an event ID was verified. Retention/access policy is owner-gated.

Process sequentially per assigned partition initially, with auto-commit disabled:

1. Validate schema, key/aggregate agreement and supported event version. Under a short local
   transaction, deduplicate the ID and lock/create the per-order observation. For a new order,
   use a unique-key upsert followed by a row lock; do not rely on locking a nonexistent row.
2. Same ID/same canonical content is replay: retain the original outcome. Same ID/different
   content or same order/version/different substantive state is a durable conflict; quarantine
   the offending source record and freeze unsent work for that order pending review. A different
   ID with the same order/version and identical content must not create another delivery purpose.
3. Record valid lower versions without regressing state or scheduling a stale READY. Check the
   retained status history for incompatible branches: READY followed by COMPLETED is valid;
   READY and CANCELLED on the same order are not a supported lifecycle under current policy.
   An incompatible branch is quarantined even if its version is greater. Gaps do not authorize
   invented transitions; accept a non-conflicting newer observation with a gap diagnostic.
4. Atomically persist the inbox outcome, accepted observation and either one READY obligation or
   an explicit no-send/suppressed outcome. A known COMPLETED/CANCELLED observation suppresses
   unsent older READY work. Never overwrite a newer version from a concurrent dispatcher.
5. Commit the database before committing Kafka's next offset (`processed_offset + 1`). Never
   commit past an earlier record whose durable write failed. If later parallel processing is
   introduced, commit only a contiguous durable prefix per partition.

A malformed/poison/conflicting message advances the Kafka position only after durable quarantine.
If PostgreSQL or quarantine persistence fails, pause that partition and retry; no offset advance.
After revoke, stop intake, finish or roll back bounded transactions, and commit only durable work
while assignment is valid. A failed/revoked commit is handled by replay, not by skipping records.
Do not blindly reset offsets to latest: a new notification group should read retained history
(`earliest` proposed), subject to approved stale-message policy. An expired committed offset or
missing retained history pauses for operator review; a reset cannot recover deleted records.

## Telegram recipient and permission contract proposal

Current User Service only exposes own-user `GET /me` and `PATCH /me` using an end-user JWT.
Its Telegram validator verifies identity but discards `allows_write_to_pm`; no durable permission
model or machine-recipient API exists. Staff accounts have no Telegram identity. A Notification
worker must not borrow a CLIENT/ADMIN token, add Telegram IDs to order events, trust a username,
or query `users_db`. The product UUID is never a valid substitute for `chat_id`.

Recommend a narrowly scoped internal User lookup, exact route/schema to be reviewed separately:
request one user UUID; return that user's private recipient identity, eligible/unknown/blocked
observation, evidence revision and observation time, without profile/credential fields. Use a
separate service principal with `notification:recipient:read`, exact issuer/audience, short lifetime
and rotated keys; current staff-role JWTs do not implement this authority. New credentials, API,
permission storage and deployment trust need approval and contract tests before implementation.

Evidence intake options:

- User Service may persist explicit permission evidence from freshly server-validated original
  initData, binding it to the verified Telegram user and this bot. Missing optional permission
  evidence means unknown, not an explicit revoke. An older signed grant must not clear a later
  blocked observation merely because it was replayed; define evidence precedence/regrant rules.
- A bot update adapter may relay `WriteAccessAllowed`, a verified private `/start`, and blocked
  observations to User through a separate authenticated, deduplicated observation interface.
  Validate private sender/chat binding; never infer the buyer from a group chat or arbitrary
  `/start` argument. Signed linking challenges would need a separate reviewed contract.
- For inbound updates, a webhook with a configured Telegram secret header and durable update-ID
  receipt is a candidate; long polling is an alternative. Acknowledge a webhook only after the
  observation is durably owned, or stage it in Notification's durable relay. Do not advance polling
  confirmation before durable receipt. Choose one intake mode; do not run competing pollers.

The browser's `requestWriteAccess` callback is UX feedback, not trusted backend proof. After a
positive callback, request fresh verified evidence or wait for the trusted bot update; do not
assume existing initData refreshes in place. Unknown/denied permission keeps delivery durably
waiting/suppressed with a reason, never a fabricated send. Fetch current eligibility before a send;
stale grants cannot guarantee that Telegram still permits it. Bot-denied delivery blocks local
retries immediately and stages an authenticated User observation; shared truth can converge later.
A later grant can resume only still-relevant work under the approved retry/expiry policy.

## Dispatch, retry and duplicate-send limits

Claim due work in a short local transaction, rechecking the per-order observation and eligibility.
Use the same local row-lock ordering as ingestion. `SKIP LOCKED` may distribute queue claims after
approval; it is not a general consistency mechanism. Commit a unique claim token and lease before
calling User/Telegram, and do not keep database locks or transactions open during either call.
If eligibility lookup needs I/O, perform it outside locks and repeat the local state/claim check
immediately before send. A changed permission revision may require relookup, not silent reuse.

Proposed bounds: 10-second external-call timeout, 60-second claim lease, one send in flight per
recipient and bounded total concurrency. These are review values, not proven service objectives.
Lease duration must exceed bounded request/cleanup time. On a hung call, stop the old process
before reclaiming ambiguous work; claim tokens prevent stale database writes but cannot fence a
Telegram request that has already escaped. A completion update must match the active claim token.

| Outcome | Durable action / retry recommendation |
| --- | --- |
| Telegram success response | Record message ID and SENT against claim; dedup prevents a new logical obligation |
| HTTP 429 / TelegramRetryAfter | Persist next attempt at or after retry-after; apply a shared bot cooldown conservatively, release claim, avoid sleeping inside transaction |
| Network timeout, connection loss, 5xx | Persist transient/possibly ambiguous outcome; proposed exponential 1–300 second backoff with jitter |
| Forbidden / blocked recipient | Stop recipient retries, mark local blocked, durably stage User observation; another user's work continues |
| Missing mapping / unknown permission | Keep explicit waiting reason, bounded recheck schedule; no send to a guessed chat |
| Bad request / malformed message | Quarantine/fail that delivery for inspection; no blind unchanged retry |
| Invalid bot token / configuration | Pause all dispatch and alert; do not misclassify every recipient as permanently invalid |

Recommend at most eight automatic send attempts and a 24-hour eligibility window from the READY
event's `occurred_at`, not its replay/receipt time, then durable exhausted/expired review. Reject
implausible future timestamps for review under an approved clock-skew bound. Both limits and grant-after-delay behavior
require owner approval; no silent deletion or unlimited replay. A server retry-after beyond the
window leads to expiry/review, never an earlier retry. Persist attempts, cooldown and deadlines so
restart cannot reset a retry budget or ignore a rate limit. Do not adopt paid broadcasts.

If Telegram accepted the message and the process lost the response or crashed before SENT,
retry can send a duplicate: Bot API sendMessage has no project-level idempotency key. A stable
event ID prevents duplicate local obligations, not exactly-once delivery to the person. Recommend
bounded retry with an explicit duplicate-risk flag; an alternative is operator review of ambiguous
sends, trading timeliness for fewer duplicates. Owner must select this policy.

The last committed READY check suppresses a known COMPLETED order before dispatch. COMPLETED
can still arrive after that check or remain unconsumed during lag. No local watermark can know
unseen terminal state, and an Order lookup would still race with Telegram; no perfect freshness
or recall guarantee is claimed. No machine Order lookup exists today. Recommend the documented
local observation policy initially; stronger requirements need a separate approved contract.

## Recovery and operations

Keep ingestion independent of Telegram availability: persist obligations while outbound dispatch
is paused. Monitor consumer lag, oldest unprocessed event, due-work age, delivery backlog,
quarantine/conflicts, claim expirations, ambiguous sends, cooldowns, exhausted attempts and
recipient-denial rate. Separate consumer/dispatch readiness from process liveness; User lookup
failure stops sending but does not discard durable ingestion. Alert before retention/retry windows
are exceeded. Exact thresholds require operational ownership and measurement.

For a crash, restart from committed Kafka offsets and replay safely; expired claims return to
review/retry only under the approved ambiguity policy. For database loss, stop intake/dispatch,
restore its backup and compare durable source offsets with broker positions before resuming.
Never advance the group beyond restored durable responsibility. If history has expired, report
a recovery gap; recreating dedup state or resetting a group can resend prior messages. Keep
inbox fingerprints at least as long as all approved Kafka/operator replay windows, including
backups; actual retention/deletion/privacy rules need approval. No purge is introduced here.

Quarantine repair records the original source, actor, reason and disposition. Do not alter a
published event, mint a fresh ID to bypass dedup or automatically replay all FAILED records.
Recheck current eligibility/status before a reviewed retry; retain an audit trail. Log event/order
IDs and sanitized codes; protect Telegram recipient IDs, event payloads and all credentials.

## Future implementation acceptance

These tests are specified, not executed notification runtime tests:

| Case | Injection / observable result |
| --- | --- |
| N1 Atomic responsibility | Kill before DB commit: offset stays; after DB commit/before offset commit: replay yields one obligation |
| N2 Contiguous offset | Fail durable write at offset n while n+1 is fetched: committed next offset never passes n; cover revoke/rebalance |
| N3 Duplicate and conflict | Replay same ID/content, alternate JSON key order, same version/new ID; no second purpose. Different content/version fork is durably quarantined |
| N4 Reorder and terminal | Deliver COMPLETED before older READY: no send; READY then COMPLETED suppresses pending work. READY/CANCELLED fork never creates a new transition |
| N5 Parallel claim | Race ingestion, two claims and terminal observation using real PostgreSQL: one active claim; no watermark regression; no SQL lock spans HTTP |
| N6 External ambiguity | Kill after Telegram acceptance/before SENT; expired lease and late response cannot overwrite current claim; document possible duplicate, not exactly once |
| N7 Failure taxonomy | Simulate retry-after, 5xx, invalid token, blocked recipient and bad message: persisted cooldown/budget, correct scope of pause, other recipients proceed |
| N8 Permission boundary | Forged browser grant, wrong user/private chat, stale grant, replayed bot update and insufficient machine scope cannot grant send eligibility |
| N9 Recovery | Restart consumer/dispatcher and restore a database snapshot; replay dedups, rate limits persist, retention gap stops for review |
| N10 Isolation | Notification owner cannot read users_db/orders_db; end-user/staff tokens cannot call the proposed internal service interface |

## Owner decisions and implementation slices

Approve or revise: Notification PostgreSQL exception and retention/backup ownership; User permission
model and service authentication; bot update intake mode; notification text/link; stale READY policy;
retry/window/lease/concurrency values; ambiguity tradeoff and operator repair ownership. These
approvals are separate from transferring design ownership. No new schema/API is committed here.

Future slices: durable inbox/state and Kafka boundaries; User-owned permission/recipient contract;
aiogram dispatcher/retry/repair with durable bot-update receipt. Each needs service-owned PRs,
real PostgreSQL/Kafka integration tests and fake Bot API failure tests after design approval.

## Sources and applicability

Official sources checked 2026-11-01: [aiokafka consumer offsets/rebalance](https://aiokafka.readthedocs.io/en/stable/consumer.html),
[aiogram error classes](https://docs.aiogram.dev/en/latest/dispatcher/errors.html),
[aiogram storage lifecycle](https://docs.aiogram.dev/en/latest/dispatcher/finite_state_machine/storages.html),
[Telegram Mini App identity and permission evidence](https://core.telegram.org/bots/webapps),
[Bot API updates and send methods](https://core.telegram.org/bots/api),
[PostgreSQL row locking](https://www.postgresql.org/docs/18/sql-select.html).
The inbox layout, evidence precedence, budgets, service scopes and recovery policy are project
recommendations, not library guarantees. Recheck exact locked aiogram/aiokafka APIs when implementing;
latest documentation may cover newer versions than the existing lockfiles. No dependency is changed.
