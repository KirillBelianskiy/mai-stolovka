# READY notification dispatch — owner decisions for #18

Status: proposal for review, 2026-11-05. No runtime change, webhook registration, credential
request or live send. This narrows the [delivery design](https://github.com/KirillBelianskiy/mai-stolovka/pull/6)
to the implemented inbox and recipient review baselines. #18 remains open.

## Decisions to approve

**D5 — uncertain delivery.** Recommended: retry a timed-out or unacknowledged `sendMessage`
with an explicit possible-duplicate flag. The total automatic budget is at most eight send
attempts within 24 hours of the original READY event's `occurred_at`, including uncertain attempts.
Use 10-second network deadlines, a 60-second claim lease and exponential backoff with jitter
bounded to 1–300 seconds. A Telegram rate limit may require waiting longer: never retry before
`retry_after`; expire if it exceeds the eligibility window. Persist attempts, expiry and shared
bot cooldown across restarts. One initial worker, one send in flight globally. No paid broadcasts.

Alternative: hold an uncertain send for operator review, with no automatic resend of that
attempt. Continue the same bounded retry policy for definitely rejected retryable requests.
This reduces duplicate risk at the cost of delayed or missed pickup messages. Neither option
guarantees exactly-once Telegram delivery: the public `sendMessage` interface documents no
caller-provided idempotency key. The stable event ID deduplicates local work only.

**D6 — permission updates, message and regrant.** Recommended: one secret-authenticated HTTPS
webhook using User's existing `POST /internal/v1/telegram/webhook` behind a separately reviewed
public ingress mapping. Notification does not receive bot updates. Keep the two recipient service
routes private; do not expose the `/internal/` namespace. A configured bot uses either webhook
or polling, never both. Long polling would require a separate durable intake and offset design;
do not add it as a fallback. Until hosting is ready, use the fake Bot API and synthetic fixtures.

Only notify a currently eligible private recipient for a still-relevant READY order. Proposed
plain-text Russian copy: **«Заказ {order_number} готов к выдаче.»** Link label **«Открыть заказы»**,
destination `https://maistolovka.me/#orders`. No order contents, identity details or credentials
in the URL. Verify that link and authenticated entry with the permitted test account under #25/#27
before enabling real delivery. If it cannot restore/enter the app reliably, review the exact bot
launch URL before rollout rather than silently changing the link.

An unknown permission may become eligible on fresh verified grant while the same READY order is
still current and within its original window. Missing mapping or absent grant sends nothing.
A definitive recipient block stops that obligation; a later verified regrant may enable future
READY obligations, never revive that blocked, expired, frozen or terminal one. A delayed block
report cannot overwrite newer User evidence. No generic HTTP error, browser callback, username,
unblock alone or prior successful message proves permission. Bot identity and credentials are
configured privately only for a separately authorized controlled test or rollout.

## Concrete implementation boundary after approval

- Inbox PR #43 `e10599381941b181b928ab8fdcc8f4fac17467d3` already durably creates one
  `ready_obligations` row per `(order_id, version)` and freezes/suppresses it on known conflicts
  or terminal states. Keep it authoritative for observed order eligibility. Propose a separate
  Notification-owned dispatch record with claim token, lease, attempts, deadlines and stable
  observation ID. Do not reinterpret `created_at` as READY occurrence time or mutate event IDs.
- Lock order observation before obligation/dispatch state, matching ingestion. Commit a bounded
  claim before external calls. Resolve User permission using the dedicated read scope, then
  recheck current order, active claim and deadline immediately before sending. Apply a completion
  only for the matching claim token. No transaction spans a network call. This cannot prevent a
  Telegram request racing with a not-yet-observed terminal event or revoke an escaped request.
- Store acknowledged message evidence only on a confirmed response. Lost ACK, timeout after
  request escape or process loss after sending follows the selected D5 policy. Treat uncertain
  5xx outcomes conservatively. Persist rate-limit wait; fail malformed permanent requests for
  review; pause on bot credential/configuration failure. Do not report a generic 403 as a user
  block. For a definitive private recipient block, persist local suppression and stage an
  idempotent User report using a separate scope, stable notification UUID and observed revision.
  Resolve revision conflict via a fresh snapshot; never force an older observation through.
- Default startup remains non-sending. A future dispatch worker is explicit and remains separate
  from inbox progress/offsets. #18 owns only Notification paths; User #16 and routing #25 keep
  their ownership. No broker topic, public proxy, User schema or shared configuration edit is
  included in this decision proposal. Record approval in a versioned skill update before runtime.

## Required dependency and acceptance evidence

User PR #46 is still at `36a689709771cfc1938171e663e4a08d74dfa43f`, with changes requested.
The [independent review](https://github.com/KirillBelianskiy/mai-stolovka/pull/46#pullrequestreview-5769707996)
reproduced two failing HTTP block-report cases: strict UUID parsing rejects the documented JSON
string, and four recipient DB tests are missing the integration marker. Require a corrected
User-owned head with all 13 session/recipient integration cases selected and passing. Do not work
around the endpoint in Notification or treat the green nine-test run as recipient acceptance.

After that and owner decisions, start test-first on the pinned inbox/recipient inputs:

| Exercise | Required observation |
| --- | --- |
| Fake Bot API success, lost ACK, timeout and restart | One local purpose; only acknowledged success records message ID; unknown outcome follows the selected policy without resetting expiry/attempts |
| Rate limit, forbidden, malformed payload and invalid token | Persist `retry_after`/cooldown; a definitive block stages one idempotent report; terminal bad input and bot-wide pause are distinct; no sensitive data in logs |
| Lease expiry, claim race, late/duplicate/terminal event | Stale claim cannot finish a new attempt; locally known terminal/frozen work never sends; late events do not create another purpose |
| Unknown, block, regrant and revision conflict | Fresh grant only releases eligible waiting work; blocked/terminal obligations never revive; stale block cannot overwrite regrant |
| Controlled HTTPS Telegram delivery | Verify the exact READY text, approved link and grant flow with explicit test-account permission; separate from fake-API tests and production approval |

Official technical reference checked 2026-11-05: [Telegram webhook and secret token](https://core.telegram.org/bots/api#setwebhook),
[sendMessage](https://core.telegram.org/bots/api#sendmessage) and
[retry_after](https://core.telegram.org/bots/api#responseparameters). The bounds and regrant
rules above are product decisions, not Telegram requirements or already approved policy.
