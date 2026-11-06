# SCRUM-26 — Mini App checkout and own order recovery

Implemented for review under product #21, stacked on #48 at 8039f50. User session #42 at
4c2e77f and Order/demo wallet #36 at 7306674 remain separate, unmerged runtime dependencies.
This branch changes the Mini App and scoped test tooling/lockfile, not backend APIs or schemas.

## Owner decisions and acceptance

On 2026-11-04 the owner answered “Да, хранить в текущей вкладке” to D9: account UUID, original
checkout request and key in sessionStorage, no tokens/card data, reuse after unknown results,
and explicit warning before deleting recovery data. The owner answered “Да, Москва / МСК”
for displayed slot times. Skill v0015 preserves these bounded choices; this does not approve
opening hours/calendar, all other D10 proposals, production retention or real-money providers.

Acceptance: persist before POST, original body/key through retry/reload, no silent second intent,
separate price confirmation, actionable slot/dish failures, own REST history/current ticket,
version-checked permitted cancellation, and private state isolation across auth changes.

Design continues the existing ivory/navy cafeteria interface in Next.js static export. The order
receipt is the signature element: large order number, visible status, historical item names/prices
and an explicit Moscow interval. No external component inspiration or new runtime dependency was
needed. Desktop long carts scroll within the existing panel; mobile navigation wraps to avoid
horizontal overflow. The final 390px viewport probe measured content/client width 375/375
(excluding its scrollbar), after an earlier 7px header overflow was fixed. There are no Next.js runtime routes/server sessions or simulated app APIs.

## Journal and uncertain results

`mai-food:checkout:v1` contains only `{version,account_id,key,body}`. The body has slot UUID, sorted
unique dish UUID/positive quantity pairs and confirmed integer-kopek total. Bounds, UUIDs, shape,
unknown fields and size are validated. Objects are frozen and the same serialized body/key is
sent on recovery; the account ID is a guard, never authentication or proof of order/payment.

Before any create call, write and read back the intent. Corrupt, foreign, occupied or unwritable
storage blocks a fresh checkout. Storage failure never falls back to a supposedly reload-safe
memory-only operation. One immediate in-memory lock suppresses overlapping button actions;
TanStack retries apply to reads only. The authenticated caller checks the original account and
never replays an old operation under another restored identity.

On timeout, malformed success, network failure, server uncertainty or auth boundary change, keep
the original intent. Reload reads it but does not automatically POST: the user explicitly restores
the original order. Cart edits cannot replace that body. A late response after account unmount
cannot clear the intent or update the new account. Foreign intents show only a generic notice;
private history/ticket caches are account-keyed and removed/cancelled when the account changes.

A known fresh rejection (for example PRICE_CHANGED or SLOT_FULL) may release the fresh intent.
A new price requires another explicit button and a fresh key. A rejection during recovery of an
already uncertain intent cannot prove that an earlier request will not finish: retain its original
body/key, even if a retry now reports a changed price. Do not silently amend or replace it.

The explicit two-action clear flow warns that an order may already exist and a new submission may
create another. Returning from the warning preserves the key. Clearing while a request is in
flight is disabled. Closing/clearing the tab can lose recovery; browser session restore or an
opener may retain/copy sessionStorage, so do not promise secure deletion on close. An independently
opened tab has no global dedup coordination. Server history remains available but an immediately
empty page does not prove that a previous in-flight request cannot complete.

## Price, status and cancellation authority

Use existing Order endpoints with an in-memory access JWT and no cookies on Order requests.
Only User session requests use its HttpOnly cookie. Slot availability and client clock are hints;
the backend decides capacity/cutoff/current prices and whether cancellation is permitted.

Validate successful order responses against account, slot, items/quantities and confirmed total.
The idempotent POST response may be an old creation snapshot: use it only to identify the order,
then GET current detail before presenting status. REST detail/history use account-bound IDs and
reject foreign/inconsistent responses. History has explicit paging, manual refresh and focus/
reconnect recovery. It can change between pages; no atomic snapshot or 30-second SLO is claimed.

The ticket displays historical snapshots, total, version-derived status and full date/time marked
МСК. The customer sees cancellation only for their PENDING order before slot start. An inline
confirmation precedes the expected_version POST. On uncertain cancellation or version conflict,
refresh authoritative detail; do not automatically cancel a newly changed state. Server idempotent
cancellation/refund rules remain authoritative. No client-side refund or balance mutation exists.

The approved demo-wallet API can reject insufficient funds and the UI explains that failure.
Balance/payment-mode UI is still #33: this unit does not claim that #21 alone completes the full
payment MVP. There is no payment provider, client ADMIN credit path or local payment proof.

## Verification evidence

Initial domain tests failed importing the absent checkout module. Current domain/contract tests
cover frozen recovery, key/body reuse, corrupt/foreign/unwritable storage, unknown/malformed results,
price conflicts, response ownership, cancellation eligibility and Moscow formatting.

| Check | Actual result |
| --- | --- |
| Node domain/API/auth/menu tests | 27 passed |
| React DOM component cases (Vitest/jsdom/Testing Library) | 10 passed: remount/lost ACK/current REST status, separate repricing/double click, rejection after unknown outcome, account change + late response, two-action corrupt-intent clear, storage failure before POST, known-success cleanup failure, version-conflict cancellation, same-account profile concurrency and logout generation boundary |
| TypeScript | Both workspaces passed |
| Static export | Mini App build passed with both test suites; final CI evidence is linked in PR handoff |
| Dependency scope | Five pinned test-only packages; existing package versions and app runtime dependencies unchanged; installed Node 22.22.2 and existing Docker Node 22.23.4 satisfy the verified test-tool engines |

The desktop in-app Chromium browser exercised the built app with exact User #46 at 36a6897 and
Order #36 at 7306674, separate generated PostgreSQL databases and synthetic signed identities.
Menu browsing and the internal menu snapshot response were controlled synthetic fixtures; Order
used its actual HTTP MenuClient and transaction implementation. Demo payments were disabled for
this unit's live fixture. This is HTTP localhost evidence, not HTTPS/domain/real Telegram evidence.

Observed real-browser cases:

- Create committed, then the local test proxy deliberately destroyed the response. The app kept
  recovery data. After reload, the original-key replay resolved one order/key/reservation. Advancing
  the order to PREPARING before recovery proved that the ticket GET displayed current state rather
  than the replayed PENDING snapshot.
- A 145-to-155 RUB server price change displayed a separate confirmation. Double click yielded
  one new order/key; the rejected-price transaction did not leave an idempotency record.
- A long sticky desktop panel initially made its action unreachable. A bounded desktop scroll
  area fixed it and actual create/recover actions then succeeded.
- The previous native confirm dialog blocked further automated input. It was replaced by explicit
  inline confirmation/clear warnings. The updated confirmation, cancellation/conflict and account
  isolation behavior passed DOM component cases; full browser clicks through those revised states
  remain a #27 follow-up. Read-only history screenshots were captured; no claim that all such
  browser interactions passed is made.

Additional live adapter checks used the same real Order API/PG: two concurrent identical create
calls returned one order, repeated concurrent cancellation changed capacity once, stale-version
cancellation returned VERSION_CONFLICT and GET showed PREPARING, own history/slots decoded, and a
foreign-account response was rejected. The fixture ultimately had four orders/four keys, one cancellation, three reservations and seven
Outbox rows. No application database, working topic or real customer was used. Fixture processes were
stopped and both generated databases were dropped; the final temporary-DB inventory was zero.

The optional localhost-only preview proxies forward the User/Order prefixes; lost-checkout mode
can discard one successful create response per key after the real service commits. They are test
utilities, not deployment routes. Fixture credentials/metadata are private and never published.

Sources checked 2026-11-04: [sessionStorage lifecycle and opener copying](https://developer.mozilla.org/en-US/docs/Web/API/Window/sessionStorage),
[TanStack cancellation](https://tanstack.com/query/latest/docs/framework/react/guides/query-cancellation),
[Vitest requirements](https://vitest.dev/guide/), [Testing Library principles](https://testing-library.com/docs/react-testing-library/intro/).
Remaining acceptance includes real Telegram/webview/HTTPS, complete #33 payments and integrated
#27 journeys, corrected recipient #46 acceptance, production routing #25 and operational #28 gates.
No merge/deployment or production-readiness claim follows.
