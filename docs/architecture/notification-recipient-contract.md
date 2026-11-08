# SCRUM-22 — Notification recipient and permission contract

Status: design proposal for owner review, 2026-11-03. This is a User-owned interface specification
for Notification to resolve an eligible recipient and report delivery evidence. No User API, schema,
database migration, credentials, or Notification caller is implemented here. It does not authorize
Telegram delivery. Related designs: [Notification delivery](https://github.com/KirillBelianskiy/mai-stolovka/blob/a790b26148ff22a6ae6e9bd41817d75fca0550d9/docs/architecture/notification-delivery.md),
head `a790b26`; [Stage 3 event contract](events.md). Baseline: product main `4fb6886`.

## Authority and data boundary

User Service is authoritative for the mapping from product `user_id` to the verified Telegram
identity and for the latest durable permission observation. Notification Service owns event
deduplication, notification eligibility, send attempts, scheduling, suppression and delivery status.
Order events contain only the product UUID; neither service may read the other's database. The
Telegram ID is a private-chat destination, not proof of write permission. A username, client profile,
order event, browser callback, or staff access token cannot authorize a send.

No user profile, full name, username, order data, JWT, bot token, or raw initData is returned to
Notification. The lookup returns the minimum delivery address and permission state. Log neither the
destination ID nor request/response bodies. At-rest encryption, access audit, retention and key
rotation require owner and deployment decisions.

## Proposed state and evidence

Per product user and configured bot identity, store:

- `telegram_user_id`: verified Telegram identity, nullable when the User account has no Telegram link.
- `state`: `unknown`, `allowed` or `blocked`. `unknown` includes absent/insufficient evidence;
  it is not consent and must not be sent to.
- `revision`: monotonically increasing integer changed atomically whenever the effective mapping
  or state changes. It supports stale-read detection; it is not a Telegram sequence number.
- `observed_at`: server receipt time for the accepted evidence, in UTC.
- `evidence_kind`: a closed enum such as `verified_init_data`, `write_access_allowed`,
  `bot_forbidden`, or `private_chat_blocked`. Never store raw evidence in the API record.
- Source deduplication metadata, protected evidence hashes, and audit retention: implementation
  details that require a reviewed User-owned storage design; do not add them implicitly here.

Evidence precedence proposal:

1. Only User Service may record identity or permission evidence. During Telegram login it may use
   `allows_write_to_pm=true` only after verifying the original, fresh initData with the configured
   bot token and binding its `user.id` to the resolved User account. A positive Mini App callback
   or parsed `initDataUnsafe` is never evidence.
2. The optional `allows_write_to_pm` field is positive-only evidence: absent means unknown, not
   blocked and not a revocation. A stale or replayed initData grant must not replace a later
   `blocked` observation. Proposed initial bound: the existing 300-second initData freshness rule;
   confirm it remains appropriate for permission updates.
3. A Bot API `WriteAccessAllowed` update can be accepted as positive evidence only after the update
   intake has authenticated the configured bot source, validated the private-chat sender binding,
   and deduplicated the Telegram `update_id`. Its route/owner (User vs Notification) is an explicit
   gate; Notification cannot write directly to User storage.
4. A definitive Bot API Forbidden/block result for the same private recipient can be reported by
   the authenticated Notification service. It changes `allowed` to `blocked` only if the supplied
   `expected_revision` still matches the current revision. This prevents a delayed failure from
   overwriting a newer grant. Non-recipient errors (bad token, network failure, rate limit, malformed
   content) must not change recipient state.
5. A later, independently verified positive grant may move `blocked` to `allowed` only when it is
   demonstrably newer than the block observation. For Bot API updates, deduplicated update ordering
   is authoritative within that source. For initData, `auth_date` must be later than the block's
   server observation time. If evidence cannot be ordered safely, retain `blocked`/`unknown` and
   require a fresh grant; never let replayed older evidence re-enable sending.
6. An explicit bot unblocked transition is not by itself a positive write grant in this contract;
   it moves `blocked` to `unknown` pending fresh positive evidence. This conservative interpretation
   is an owner decision and should be checked against the chosen Bot API update flow.

`allowed` is a recent observation, not a guarantee that a later Telegram send will succeed. A
Forbidden response may race with a grant, account change, or delivery. Notification must still
handle the actual send result and must never infer exactly-once delivery or permanent permission.

## Proposed HTTP interface

The route names and schemas below are proposals for review, not exported OpenAPI contracts.
They require a dedicated machine-authentication design and an explicit owner decision before
implementation. Do not expose these routes through the public Mini App or kitchen origins.

### Resolve one recipient

`GET /internal/v1/notification-recipients/{user_id}`

Required authentication: dedicated Notification service principal, exact issuer/audience and
short-lived credential, with only `notification:recipient:read`. Current end-user/staff JWTs are
not accepted. Network location alone is not authentication.

`200 OK` for an existing product user:

```json
{
  "user_id": "<product UUID>",
  "state": "allowed",
  "telegram_chat_id": 123456789,
  "revision": 7,
  "observed_at": "2026-11-03T12:00:00Z",
  "evidence_kind": "verified_init_data"
}
```

For `unknown` or `blocked`, `telegram_chat_id` is `null`. If the product user has no verified
Telegram identity, return `state: "unknown"`, `telegram_chat_id: null`, and an optional bounded
reason `identity_unavailable`; do not disclose staff credentials or profile fields. Return `404`
for an unknown product UUID; return `401/403` for missing/invalid principal or insufficient scope.
Notification treats non-200, `unknown`, and `blocked` as no-send outcomes and persists the outcome
under its own durability policy.

This read is a snapshot, not a lease or reservation. The permission may change after the response;
the sender must handle Telegram's actual response and report only definitive recipient-level evidence.

### Report a definitive recipient block

`POST /internal/v1/notification-recipients/{user_id}/blocked`

Required scope: `notification:permission:report`, distinct from lookup. The body contains no raw
Telegram response or bot credential:

```json
{
  "expected_revision": 7,
  "telegram_user_id": 123456789,
  "notification_id": "<Notification-owned UUID>",
  "reason": "bot_forbidden"
}
```

The User service verifies the UUID-to-Telegram-ID binding and applies the state change in one local
transaction. The proposed idempotency key is `(notification_principal, notification_id, reason)`;
same key/same body returns the original result, same key/different body returns `409 IDEMPOTENCY_CONFLICT`.

- `200 OK`: resulting `state`, `revision`, `observed_at`; repeated identical reports are idempotent.
- `404 USER_NOT_FOUND`: no such product UUID; reveal no extra identity information.
- `409 REVISION_CONFLICT`: current observation changed; include only current revision/state. Notification
  must re-resolve and must not blindly retry the stale block.
- `409 IDENTITY_MISMATCH`: supplied Telegram ID does not match the currently linked identity; no state
  change.
- `422 INVALID_OBSERVATION`: reason is not an approved definitive recipient-level failure.
- `401/403`: invalid principal or insufficient reporting scope.

If delivery evidence arrives without a stable Notification ID, treat it as non-idempotent input and
do not update shared state until the event is deduplicated locally. User owns the canonical state;
Notification retains its own audit of the attempted send and response class.

## Permission evidence intake

Two candidate routes can establish positive evidence; choose one initial route and avoid competing,
uncoordinated Bot API update consumers:

1. **Verified Mini App initData:** User login validates raw initData and persists a true
   `allows_write_to_pm` observation with identity in the same User-owned transaction. Missing field
   leaves state unchanged. A false value, if ever supplied, is not interpreted as a block until its
   semantics are verified and owner-approved.
2. **Authenticated Bot API update intake:** one designated service receives updates via either
   webhook or long polling, not both. It verifies the configured webhook secret when webhooks are
   selected, validates private sender/chat identity, deduplicates `update_id`, and records durable
   receipt before acknowledging the update. User remains the only writer of permission state.
   The exact service that owns this intake, authenticated handoff, update durability, and retry on
   User unavailability require a separate owner decision.

A private `/start` can establish that the user interacted with the bot, but whether it grants this
product's specific notification permission is a policy decision. Do not infer a grant from a group
chat, arbitrary start parameter, username match, or `my_chat_member` event without reviewing its
meaning and binding. Do not call Telegram to test eligibility by sending a speculative message.

## Error, privacy, and availability behavior

- Fail closed: lookup outage, stale state beyond an owner-approved freshness window, unknown state,
  missing identity, and scope failure all mean no send. Queue/retry responsibility remains in
  Notification Service; User availability must not cause event loss or Kafka offset advancement
  before durable responsibility has transferred.
- Distinguish `unknown`, `blocked`, `identity_unavailable`, `revision_conflict`, and transient
  `dependency_unavailable` without returning profile data or secrets. Error bodies use stable codes;
  HTTP status/code mapping must be frozen in the OpenAPI contract before clients are implemented.
- Rate limits, batch lookup, caching, freshness TTL, service token lifetime, key rotation, audit
  retention, and request quotas remain owner decisions. Begin with single-user reads to minimize
  blast radius and avoid oversized/bulk identity disclosure.
- User lookup and observation writes must not occur inside Order Service transactions. Notification
  calls User before an external Telegram send and reports a definitive blocked outcome after the
  call; it must tolerate a permission change in between and preserve the send's ambiguity window.

## Acceptance cases before implementation

1. Valid fresh initData with verified `allows_write_to_pm=true` maps to the same CLIENT's Telegram
   destination and increments the permission revision; forged, stale, mismatched, or client-parsed
   identity cannot grant.
2. Absent permission evidence remains `unknown` or preserves the prior state; it never revokes a
   grant or creates a destination. Staff accounts and clients with no Telegram link return no address.
3. A Bot API `WriteAccessAllowed` can grant only through the selected authenticated intake; duplicate
   update IDs are idempotent, malformed/unbound/group-chat evidence is rejected.
4. A definitive block report with the current revision blocks; network errors, 429, invalid bot
   configuration and malformed messages do not. A duplicate report has one state effect.
5. A stale `expected_revision` block report cannot overwrite a later grant; a grant older than a
   block cannot unblock it; a demonstrably newer positive grant follows the selected regrant policy.
6. Missing/unknown/blocked recipient lookup never returns a sendable chat ID. A current allowed
   response still does not bypass Telegram error handling.
7. End-user/staff credentials, wrong audience, wrong issuer, expired service credentials and
   missing scopes fail closed. Public routes cannot access internal recipient data.
8. User database outage does not lose a Notification event or advance its Kafka offset before durable
   responsibility is recorded; recovery re-resolves eligibility before dispatch.
9. Responses/logs omit full profiles, initData, bot tokens, JWTs, and raw Telegram error bodies;
   recipient identifiers do not appear in metric labels.

These are future acceptance requirements, not executed tests or approved policy. User schema/API,
M2M authentication, permission evidence source, Bot API intake, and storage/retention remain owner
gates. No runtime work starts under this document.

## References

- [Telegram Mini Apps: initData and `allows_write_to_pm`](https://core.telegram.org/bots/webapps), checked 2026-11-03. Telegram instructs servers to validate raw `initData`; `allows_write_to_pm` is optional and positive-valued.
- [Telegram Bot API: `WriteAccessAllowed` and update delivery](https://core.telegram.org/bots/api), checked 2026-11-03. Updates can signal write access and private-chat block/unblock changes; webhook and long-polling update intake are mutually exclusive.
- Product contracts: `docs/architecture/authentication.md`, `docs/architecture/data-ownership.md`, `docs/architecture/events.md`, and `packages/contracts/events/envelope-v1.schema.json` at baseline `4fb6886`.

The endpoint names, state machine, revision checks, evidence precedence, scopes and error semantics above are project proposals. Telegram's interface does not supply this project's durable permission store or cross-service authorization contract.
