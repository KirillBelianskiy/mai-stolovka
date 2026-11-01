# Mini App and Kitchen integration — SCRUM-16

Status: design proposal for owner review, 2026-11-01. Product baseline `4fb6886`; no UI, API,
WebSocket or browser tests are implemented here. `kirill_bel` completes this task sequentially
after the owner ended Misha's participation. This is sole-author cross-design reconciliation,
not independent frontend peer approval.

Starting contracts: [User OpenAPI](../../packages/contracts/openapi/user-service.v1.json),
[Menu OpenAPI](../../packages/contracts/openapi/menu-service.v1.json),
[Order OpenAPI](../../packages/contracts/openapi/order-service.v1.json),
[authentication](authentication.md) and current [order policy](order-lifecycle.md).
Read proposed [WebSocket PR #3](https://github.com/KirillBelianskiy/mai-stolovka/pull/3) at `095d51e`
and [Notification PR #6](https://github.com/KirillBelianskiy/mai-stolovka/pull/6) at `a790b26`.
Their new transport, permission and operational decisions remain unapproved.

## Deployment and page boundaries

Keep two Next.js App Router static exports, local origins `http://localhost:8080` (Mini App) and
`http://localhost:8081` (Kitchen), same-origin `/api/v1/*` through NGINX. Production Telegram use
requires HTTPS/BotFather configuration. Do not put bot tokens, signing keys or service credentials
in `NEXT_PUBLIC_*`, HTML, bundles or browser storage. No Next.js server actions, runtime route
handlers, server sessions or default server image optimization. Existing `images.unoptimized`
and `trailingSlash` stay compatible with static hosting.

Use fixed exported pages for menu, cart, checkout, order history/detail and profile; represent a
runtime order ID in a query parameter on a fixed detail page, not an unbounded `/orders/[id]`
route requiring unknown build-time params. Parse search parameters in a client component within
the appropriate Suspense boundary. Static server output never contains private API responses.
API redirects and trailing slashes must match the proxy/OpenAPI mapping below.

Kitchen has fixed login, queue, detail and ADMIN menu/slot views, with responsive Android-tablet
layouts. An eventual native Android client remains a separate decision. Keep Russian UI, established
ivory/navy/blue tokens, local shadcn components, accessible labels/focus/error states and touch-sized
actions. Penpot supplies visual context only. No payment, maps, multi-cafeteria or prototype features.

## Existing API mapping

Paths below are external proxy paths; OpenAPI paths are service-relative.

| Flow | Current method/path | Authorization and behavior |
| --- | --- | --- |
| Telegram login | POST `/api/v1/users/auth/telegram` | Original `{init_data}`; verified server-side; always client identity |
| Staff login | POST `/api/v1/users/auth/staff` | `{username,password}`; provisioned staff accounts only |
| Profile | GET/PATCH `/api/v1/users/me` | Own Bearer identity; PATCH only full_name |
| Categories | GET `/api/v1/menu/categories` | Public; ordered categories |
| Available menu | GET `/api/v1/menu/items`; GET `/api/v1/menu/items/{id}` | Public; category_id/limit/offset on list, unavailable item yields 404 |
| Cart validation | POST `/api/v1/menu/item-snapshots` | Existing batch `{item_ids}`; current names/prices/availability, not a quote/reservation |
| Slots | GET `/api/v1/orders/slots` | Bearer; future slots by default; includes remaining_capacity, not a reservation |
| Create order | POST `/api/v1/orders/` | CLIENT, UUID `Idempotency-Key`, items/slot_id/expected_total_amount |
| History/queue | GET `/api/v1/orders/` | CLIENT is owner-filtered; staff can see orders; status/slot_id/limit/offset filters |
| Order detail | GET `/api/v1/orders/{id}` | Owner or staff; foreign client order concealed as 404 |
| Status change | PATCH `/api/v1/orders/{id}/status` | Staff with exact transition role; `{status,expected_version}` |
| Cancel | POST `/api/v1/orders/{id}/cancel` | Owner/ADMIN under status/time policy; `{expected_version}` |
| Admin menu | GET `/api/v1/menu/admin/items`; POST/PUT/DELETE categories/items | ADMIN; admin list includes unavailable items, unlike public list |
| Admin slots | POST `/api/v1/orders/slots`; PUT/DELETE `/api/v1/orders/slots/{id}` | ADMIN; referenced slots have time/delete restrictions |
| Kitchen hints | WS `/api/v1/ws/kitchen` | Reserved, not implemented; proposed first-frame staff JWT below |

There is no HTTP staff signup, password reset, role-management UI API, refresh/logout API,
payment API, notification permission-status API or browser replay cursor. Staff provisioning/reset
uses the existing operator CLI. Do not show unsupported controls as working. Menu writes are PUT
full replacements, not PATCH; slot timestamps must be timezone-aware and capacity is integer orders.
Slot list is an array with limit/offset, not the OrderPage wrapper; stop pagination on a short page.
Menu/Order lists use items/total/limit/offset; changing filters resets pages.

## Authentication and browser state

Recommend access tokens in memory only. JWTs are not persisted with Zustand, Query or the checkout
journal. Staff enter a password at login and again after expiry/reload; do not store it. A remembered
staff session would require a separate reviewed server-session/cookie design, not localStorage.
Default JWT lifetime is 900 seconds, but use actual response expiry and handle server 401; client
clock/decode is only a UX hint, never authorization. Menu/Order verifiers cannot revoke a token
immediately after role/password changes; disclose the current lifetime boundary.

Mini App initializes the installed `@tma.js/sdk-react` adapter on the client only, with capability
checks and explicit unsupported/outside-Telegram UI. Send the original raw initData, never a parsed
user object or initDataUnsafe as authority. No fake development login in production. Reauthentication
may reuse still-fresh data only within server rules; a five-minute-old launch cannot be renewed by
changing auth_date. If fresh verified initData is unavailable, ask the person to reopen the Mini App.
Do not presume requestWriteAccess refreshes initData. Notification permission is distinct from login:
show a separate optional prompt/capability fallback; positive UI callback is not backend proof. Until
SCRUM-14's User contract is approved/implemented, do not claim delivery is enabled or guaranteed.

On logout, expiry or identity change: disable private queries/mutations, close the socket, cancel
in-flight fetches, clear private Query data and account-scoped Zustand/UI state, then return to auth.
Use an auth-generation identifier in callbacks so old responses cannot repopulate another account's
cache; aborting fetch does not undo a committed server mutation. Existing logout is client cleanup,
not token revocation. Never log passwords, initData, access frames or Authorization headers.

| State | Owner / proposed persistence |
| --- | --- |
| Menu, profile, slots, orders, admin lists | TanStack Query; private keys include user UUID, role/auth generation, filters and page; no persisted private cache |
| Cart quantities, selected slot, drawer/filter intent | Zustand/local state; no authoritative prices, reservations or order statuses |
| Access JWT and password input | In-memory auth scope; password cleared after submission; no persistent credential storage |
| Uncertain order creation | Separate account-scoped, schema-validated checkout intent journal; proposed sessionStorage, owner review required |
| Socket status and dirty generation | Connection-local state; discard on logout/close; no durable replay cursor |

Suggested Query keys: `['orders', userId, role, authGeneration, filters, page]` and
`['order', userId, role, authGeneration, orderId]`. Public menu may use category/page keys without
an identity. Include every response-shaping parameter. Wire Query's AbortSignal into fetch;
credential changes invalidate outstanding callbacks as well as cache entries. Avoid duplicating
server entities in Zustand. Do not add a shared UI abstraction until actual reuse appears.

## Mini App checkout, changed prices and uncertain requests

1. Load categories/menu, maintain one cart line per dish UUID with a positive integer quantity.
   Names/prices in the cart are display estimates only. Respect request limits (at most 100 distinct
   lines) and safe integer arithmetic; server total is authoritative, never accept a floating price.
2. Before confirmation, fetch current batch menu snapshots and future slots. Handle unavailable
   dishes explicitly and show the updated integer-kopeck total formatted for the person. A snapshot
   has no quote token and reserves neither price nor capacity. Recheck selected slot after refetch.
3. After explicit confirmation, create one UUID key for the immutable intent: selected slot, sorted
   unique item IDs/quantities and expected total. Freeze it while unresolved, disable duplicate taps
   and write the journal before sending. Do not generate a fresh key inside a retry function.
4. POST the exact confirmed body/key. On 201, retain the order ID, finish the journal, clear only
   the submitted cart intent, invalidate history/slots and GET current order detail. A replayed 201
   returns the ORIGINAL creation response, possibly PENDING even when the current order is already
   READY/CANCELLED. Do not overwrite newer detail with that creation snapshot.
5. On timeout/lost connection/ambiguous 5xx, keep the intent unresolved and retry the identical
   key/body after bounded backoff or reauthentication of the same user. Do not let a subsequent
   button silently submit a new intent while the first outcome is unknown. A history match is
   helpful for the person, not a proof that a particular key failed or succeeded.
6. A definitive PRICE_CHANGED (409) returns `detail.total_amount`, not an itemized quote. Refetch
   menu snapshots, show any changed names/prices/unavailable lines and require a fresh confirmation.
   If the displayed refetched total differs again, confirm that value and let the server recheck;
   never silently accept either conflict total. A definitively rejected transaction did not consume
   the key, but recommend a fresh key for the newly confirmed intent; never change a successful or
   unresolved key's body. An unresolved old intent must be resolved before creating the new one.
7. On success/definitive failure, offer a clear next step. Do not treat disabling a button, a network
   abort or closing the page as server cancellation. Do not queue automatic offline order writes.

The proposed journal contains schema version, account UUID, idempotency UUID, exact request body,
intent time and state; no token/password/initData or full response/profile. sessionStorage supports
same-tab reload recovery but is JavaScript-readable and untrusted: validate shape, size, UUIDs and
account binding before use. Storage failure must be shown before submit or require an explicit
in-memory-only fallback warning; do not promise reload safety when the write failed. Closing the
tab/clearing storage loses this recovery path. On forced logout/clear, warn about unresolved work,
clear private data, and require history/manual reconciliation before a new order; do not invent a
server lookup-by-key API. Persistent or cross-device intent recovery needs a separate contract.

## Errors and employee operations

| Result | User behavior / retry boundary |
| --- | --- |
| 401 | Stop protected retries/socket reconnect; clear credentials and reauthenticate; preserve unresolved key/body only within the approved same-user recovery policy |
| 403 | Deny the action, refresh identity if appropriate; never switch roles or retry with another token |
| 404 | Show missing/unavailable item or order; foreign order IDs reveal no owner information |
| 409 PRICE_CHANGED / ITEM_UNAVAILABLE | Refresh cart snapshot; explicit confirmation or remove unavailable lines |
| 409 SLOT_FULL / SLOT_CLOSED / SLOT_STARTED | Refresh slots/order; select an eligible alternative, no capacity optimism |
| 409 IDEMPOTENCY_CONFLICT | Stop; existing key was bound to another payload. Reconcile original intent rather than silently issue a new key |
| 409 VERSION_CONFLICT / INVALID_TRANSITION / CANNOT_CANCEL | Refetch detail and list membership; show current state, no blind mutation retry |
| 409 CAPACITY_CONFLICT / SLOT_HAS_ORDERS | Keep admin form values; explain referenced-slot restriction, no destructive workaround |
| 422 | Map field validation safely; do not automatically repeat unchanged invalid data |
| 429 | Respect Retry-After if provided; otherwise bounded cooldown. Avoid automatic login loops |
| 503 MENU_UNAVAILABLE / SNAPSHOT_EXPIRED / IDEMPOTENCY_RETRY or transport failure | Show recoverable status; uncertain creation uses same key/body, reads may retry with bounded jitter |

FastAPI errors may have string or structured `detail`; parse known codes and provide a sanitized
Russian fallback. HTTP success is still schema-checked. Cache-bypass private requests; no offline
private-data service-worker cache. Use loading/empty/error/stale indicators rather than blank pages.

Kitchen queue shows current orders by existing status/slot filters with stable order IDs and
versions. COOK/ADMIN advance PENDING -> PREPARING -> READY; CASHIER/ADMIN advance READY ->
COMPLETED. CLIENT cancels own PENDING; ADMIN may cancel PENDING/PREPARING before slot start.
READY -> CANCELLED is not supported. Buttons reflect these permissions, but REST remains the
authority. Display server timestamps explicitly; browser time never grants cancellation rights.

Each mutation sends the displayed expected_version and serializes actions per order locally.
On a timeout, GET current state before another mutation; never optimistically declare success or
roll back an already accepted change because the response was lost. Invalidate detail, affected
queue membership, history and slots after cancellation. Menu admin supports unavailable items and
full replacement writes. Slot admin respects current_orders and immutable referenced times; menu
edits never rewrite historical order item names/prices. Show kopecks/timezones accurately.

## WebSocket reconciliation contract review

Self-reconciled with SCRUM-15 head `095d51e`: no new wire fields proposed here. Staff connection
states are disconnected -> authenticating -> synchronizing -> live; every close clears live status.
Use native browser WebSocket, `wss` in production, exact Kitchen origin and no token in URL.

- Install message/close handlers before any queue fetch, open the socket and send first frame
  `{"type":"auth","access_token":"<current staff JWT>"}`. No arbitrary Authorization header is
  assumed. Server deadline 5 seconds and frame cap 12 KiB are proposed; do not send client commands.
- Wait for `ready` with protocol_version=1 and diagnostic connection_id. Server queues ready before
  broadcast visibility, using one socket writer. ready is not a replay cursor or durable snapshot.
- Fetch required REST pages while retaining a bounded dirty-order set plus generation counter.
  `orders.changed` carries event_id/order_id/order_version/event_type only. Coalesce hints; a bound
  overflow triggers whole-list reconciliation, not silently clearing dirty state. Unknown order/version
  gaps require current REST; receiving a hint never authorizes an order mutation.
- Compare fetch-start generation with the current generation. Refetch dirty detail AND filtered
  membership until stable enough to present the latest view; do not drop hints when replacing pages.
  Reject older detail versions from overlapping requests. A newer mutation response is not replaced
  by a stale REST/creation response. Reset/invalidate pages after membership changes; existing offset
  pagination is not an atomic multi-page snapshot, even after one quiet generation pass.
- On 1013/outage/backpressure or ordinary disconnect, show stale/polling state and reconnect with
  proposed 1–30 second jittered backoff; repeat ready-then-REST after reconnect. Auth close 4401
  requires staff login, 4403 stops retry. 1008/protocol mismatch stops and reports a client/protocol
  error instead of looping. Clear timers/old handlers when auth generation changes.
- Proposed visible REST refresh every 30 seconds plus focus/online refresh repairs lost hints.
  A failed WS must not prevent authorized REST reads/actions; show that live delivery is unavailable.
  Browser visibility/network state is a hint, not a reliable server-health proof. No Socket.IO or
  client ping-frame API. Missing/reordered hints and broker/service restart converge via REST.

Mini App order status initially uses REST polling/focus recovery; it cannot subscribe to the
staff-only Kitchen endpoint. Telegram readiness notification is supplemental and never the sole
source of order status. The UI does not claim immediate delivery or exactly-once updates.

## Alternatives, owner gates and execution slices

Recommend in-memory credentials and explicit re-login over localStorage JWT persistence; recommend
an account-scoped sessionStorage intent journal over unsafe fresh keys after reload. A backend
HttpOnly session could improve session UX but needs a separate server/security contract; static
Next.js alone does not provide it. Recommend REST as canonical state and minimal WS invalidation
over a second full-order cache. Keep local UI components until reuse warrants extraction.

Owner review required: credential/re-login and intent persistence UX; browser storage/privacy and
forced-logout recovery; proposed WebSocket messages/limits; notification permission/status UI;
freshness/periodic polling targets and timezone display. Existing role/cancellation/price rules stay
confirmed. No new schema, API or design-prototype business requirement is approved by this document.

Future slices: Mini App auth/menu/cart; checkout/history/profile with idempotent recovery; staff
auth/queue/role mutations; menu/slot admin; WS reconnect/Query reconciliation after SCRUM-15 approval.
Test browser behavior against existing APIs plus approved wire contracts, including static deep
links. No frontend implementation starts as a side effect of finishing this design.

## Future acceptance specifications

| Case | Observable acceptance |
| --- | --- |
| F1 Static deployment | Both exports build without server features; fixed detail deep link works with a runtime UUID; no private data/secret in assets |
| F2 Auth lifecycle | Real raw initData accepted through backend; outside/stale Telegram sessions get explicit UX; expired staff token returns to login without loop |
| F3 Identity switch | Delayed fetch/mutation/socket callback from A cannot populate B's private cache; tokens/passwords absent from storage/logs |
| F4 Cart and slots | Unavailable/deleted dish, changed price, full/started slot and integer overflow show correct action without creating an order |
| F5 Explicit price | PRICE_CHANGED total differs from refreshed cart again: display/refetch/reconfirm; no automatic revised-total submission |
| F6 Uncertain creation | Drop 201 after commit, reload same tab and retry journal key/body: one order; replayed PENDING never regresses current READY/CANCELLED detail |
| F7 Journal failure | Malformed/other-user journal and storage quota/disabled storage cannot trigger a send; lost journal never silently generates a replacement checkout |
| F8 Mutation roles | COOK cannot complete/cancel, CASHIER cannot prepare, READY cannot cancel; owner/ADMIN cutoff and expected_version conflicts handled |
| F9 Reconcile race | Hint before/during/after REST, filtered-list move and stale response converge; dirty-set overflow refetches all, no invented atomic snapshot |
| F10 Disconnect/expiry | 1013/restart/backpressure refetches after ready; 4401/4403/1008 stop inappropriate retries; REST fallback remains usable |
| F11 Admin contracts | PUT sends full item; unavailable admin list works; capacity/time/delete restrictions preserve referenced order history |
| F12 Permission UX | Denied/unsupported write access leaves ordering usable and notifications unconfirmed; browser callback alone never displays backend permission as verified |

These are unexecuted future browser tests. Current validation checks document/API mapping and
schema consistency; product PR CI tests the existing baseline, not future UI functionality.

## Sources

Official sources checked 2026-11-01: [Next.js static exports](https://nextjs.org/docs/app/guides/static-exports),
[TanStack Query keys](https://tanstack.com/query/latest/docs/framework/react/guides/query-keys)
and [cancellation](https://tanstack.com/query/latest/docs/framework/react/guides/query-cancellation),
[Zustand persist controls](https://zustand.docs.pmnd.rs/reference/middlewares/persist),
[Telegram Mini Apps](https://core.telegram.org/bots/webapps),
[browser WebSocket API](https://developer.mozilla.org/en-US/docs/Web/API/WebSocket/WebSocket),
[sessionStorage lifecycle](https://developer.mozilla.org/en-US/docs/Web/API/Window/sessionStorage).
The flows, journal, limits and reconciliation algorithm are project recommendations; library defaults
do not provide these product guarantees. Check exact locked SDK APIs during implementation.
