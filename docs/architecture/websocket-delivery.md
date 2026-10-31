# Stage 5 employee WebSocket design — SCRUM-15

Status: proposed design, 2026-10-31, pending owner approval and frontend READBACK on SCRUM-16.
Owner: kirill_bel. Product baseline: 4fb6886. No endpoint, Kafka consumer or frontend code is
implemented here. SCRUM-12 coordinates; SCRUM-13 defines the proposed event publication contract.

## Boundary and recommendation

Keep native WebSocket at the reserved WS /api/v1/ws/kitchen interface. Order REST remains the
canonical state and the only mutation interface. WebSocket sends change hints, not a durable
client-side order database. COOK, CASHIER and ADMIN may subscribe; CLIENT is denied. Existing
REST roles still govern each status/cancellation action; receiving a hint grants no extra privilege.

Start with one instance and the existing RS256 public-key validation contract. Browsers expose
URL/subprotocol parameters rather than an arbitrary Authorization header in the WebSocket API.
Recommend an application authentication message as the first frame, avoiding bearer tokens in
URLs and preserving static Next.js deployment. Alternatives are discussed below. All values here
are proposed protocol choices; the current reserved endpoint continues to reject connections.

## Proposed handshake and messages

1. Validate the exact Origin against an environment allowlist before upgrade. Reject absent/null
   origins for this browser-only endpoint. Local Kitchen origin is http://localhost:8081; production
   must explicitly configure its HTTPS origin. Origin is a browser boundary, not authentication.
2. Permit an unauthenticated transport for at most 5 seconds, with a 12 KiB total-frame limit,
   strict frame parsing and connection limits per deployment. Do not register it with the kitchen
   hub, send order hints or accept commands before authentication.
3. Client first frame: {"type":"auth","access_token":"<current staff access JWT>"}. Validate the
   existing fixed RS256 algorithm, issuer/audience, kid, required claims, expiry and staff role.
   No private key is distributed. Invalid/missing/CLIENT tokens close with application code 4401
   (unauthenticated) or 4403 (forbidden); never echo credentials or log frame bodies.
4. Establish the subscription and queue
   {"type":"ready","protocol_version":1,"connection_id":"<UUID>"} as one ordered hub operation.
   Queue ready before making the authenticated connection visible to broadcasts; do not await
   network I/O in that registration operation. One writer per connection drains the outbound
   queue, so ready is always the first application response and later hints cannot overtake it.
   The subscription exists before ready reaches the browser. Kafka consumer initialization must
   already be complete; otherwise close 1013 for temporary unavailability. The connection ID is
   diagnostic only, not a replay cursor, authorization credential or durable session.
5. A validated domain event produces a hint such as
   {"type":"orders.changed","event_id":"<UUID>","order_id":"<UUID>",
   "order_version":2,"event_type":"ORDER_STATUS_UPDATED"}.
   No user profile, full order contents or token is sent. Client GETs current authorized REST state.
6. Re-auth frames, client mutations, subscriptions to arbitrary users and unknown message types
   are rejected (1008). Version 1 has no resume cursor or replay promise. Schema proposals must
   receive frontend review before a coordinator adds language-neutral contracts.

The 12 KiB total-frame cap leaves JSON overhead above the existing 8192-character JWT bound.

Close at token exp (4401), including a connection that is otherwise idle. The frontend reauthenticates
through the existing staff login API and opens a new connection; there is no implemented refresh
endpoint. Do not invent persistent login or token renewal. Role/account changes remain bounded by
the current 900-second token lifetime until a separate revocation design is approved. Log out closes
the socket and clears client state. Reconnect must not spin on expired credentials.

## Kafka delivery and backpressure

Proposed topic/key/envelope follow SCRUM-13: orders.events.v1, order UUID key, v1 events with
order_version. Use kitchen-orders-v1 as an independent group from Notification. A single instance
may use that group; replicas sharing it would split the stream and miss hints for each other's
clients. Future multiple instances require per-instance groups or an approved fan-out design;
per-instance groups are preferred over adding new infrastructure, with explicit group cleanup and
replay policy. This stage does not deploy replicas or create groups.

Validate event schema/type/version before broadcasting. Invalid events alert and stop consumption
pending reviewed quarantine/recovery policy; do not loop silently or expose malformed contents.
After a valid event is enqueued (or no staff are connected), commit its Kafka offset. A process
crash may lose queued hints; disconnected clients restore state via REST. That is an explicit
best-effort notification contract, not durable end-user delivery. New instances use a documented
consumer start-offset policy and never treat the consumer offset as the browser's state cursor.

Propose at most 128 queued hints per authenticated connection. Coalesce queued hints for the same
order by version where possible; on overflow close that client with 1013 rather than blocking the
consumer or growing memory indefinitely. Drop duplicate event IDs within a bounded in-memory
cache only as an optimization. Correctness still relies on canonical REST and client versions;
there is no permanent dedup store for ephemeral WebSocket hints.

Use server WebSocket ping/pong (proposed 20-second interval and 20-second timeout) and proxy idle
timeout above that interval; no custom browser ping frame API is assumed. On Kafka consumer failure
or reinitialization close current clients with 1013 so they resubscribe and resynchronize; do not
leave a misleading healthy live channel. Pause/new connections until consumer initialization
succeeds. Liveness is process-only; readiness reflects consumer/hub availability, not just HTTP.

## REST recovery without a subscribe/fetch gap

The frontend owner should implement this protocol after approval:

1. Obtain staff auth, connect and wait for ready. Install the event handler before starting REST.
2. Fetch the required queue pages through GET /api/v1/orders with the existing status/slot filters.
   While fetching, retain a bounded dirty-order set/generation counter for received hints.
3. If hints arrived during the fetch, invalidate/refetch affected records AND queue membership;
   a changed status can add/remove an order from filtered lists. Refetch whole filtered lists when
   membership is uncertain. Do not discard the hints when replacing cached results.
4. If no new hints arrived during reconciliation, mark the view live. During continuous changes,
   show the latest available view plus a synchronizing indicator and keep reconciling; do not
   promise a point-in-time multi-page snapshot, which current REST does not provide.
5. Ignore lower/equal order versions when updating a known record. A version gap or unknown order
   triggers REST reconciliation; never infer unseen intermediate statuses from a gap.
6. On close, clear live indication, reconnect with jittered exponential delays (proposed 1–30 seconds),
   then repeat subscribe-before-fetch. Auth failures require login, forbidden stops retry, and
   background resume/online events trigger another reconciliation. Periodic REST refresh (proposed
   30 seconds while visible, plus focus/online) covers silent hint loss and displays eventual truth.

This prevents a permanently missed change solely from fetching before subscription. It does not
provide an atomic Kafka+REST snapshot or a durable replay log to browsers. Existing per-order
versions help reject stale data, while REST list pagination is still eventually consistent under
concurrent writes. If the business needs strict queue snapshots, propose a revision/cursor API
separately rather than quietly extending Order Service in frontend code.

## Alternatives, approval gates and implementation units

- Query-string JWT: simple handshake but bearer credentials can enter URLs/access logs; reject.
- Short-lived single-use WebSocket tickets: stronger bounded handshake credentials, but requires
  an approved issuing API/durable replay design; defer unless first-frame auth is rejected.
- Secure HttpOnly cookies: possible with backend session/CSRF/origin design, but current auth
  returns Bearer tokens and the static frontend has no server session. Do not assume cookies exist.
- Socket.IO: adds a different protocol without an approved need; keep native WebSocket.

Owner approval gates: first-frame auth/throttle limits, origin list, close-code conventions, token
revocation limitation, wire messages, offsets/poison handling, queue limits and freshness targets.
SCRUM-16 must READBACK authentication and reconciliation assumptions; SCRUM-13/SCRUM-14 must
review shared topic/group boundaries. New wire contracts are proposals only, not committed schemas.

Future implementation units: connection/auth lifecycle with unit tests; consumer/hub adapter with
Kafka integration tests; bounded per-client delivery; frontend reconnect/REST reconciliation tests.
Each needs its own implementation ticket after design approval; runtime changes are not authorized
by completing this design task.

## Future acceptance scenarios

- Reject bad origin, absent/expired/wrong-signature/wrong-audience/CLIENT credentials; send no
  hints before auth; close idle unauthenticated sessions and active expired-token sessions.
- Staff roles receive hints but their REST mutations still enforce the existing role matrix.
- Broadcasts racing with registration cannot precede ready or be lost between subscription and
  ready. Exactly one socket writer preserves queue order; no hub lock spans network I/O.
- Events before/during/after REST fetch and status-filter membership changes eventually converge;
  old/duplicate/out-of-order versions do not roll a record backward.
- Reconnect after consumer/service/browser restart resubscribes and fetches REST; no browser
  resume/exactly-once claim. Lost hints are corrected on periodic/focus refresh.
- Slow-client queue overflow closes only that connection; memory and consumer progress stay bounded.
- Kafka outage invalidates live state; recovery creates a fresh ready+reconcile cycle.
- An expiration close returns to staff login without an infinite reconnect loop; logs contain no JWT.
- Tests with two future instances prove broadcast semantics; a shared-group negative test exposes
  partition splitting rather than accepting it as fan-out.

These are future tests, not executed runtime checks. Design validation is review against current
contracts, size/lifecycle consistency and product PR CI. Operational metrics should include active
and unauthenticated connections, auth failures, queue depth/overflow closes, consumer lag, reconnect
rate and time-to-reconciled-view; tune thresholds from measurements before production.

## Sources

Official sources checked 2026-10-31: [WHATWG browser WebSocket interface](https://websockets.spec.whatwg.org/),
[FastAPI WebSocket dependencies/lifecycle](https://fastapi.tiangolo.com/advanced/websockets/),
[Kafka consumer design](https://kafka.apache.org/41/design/design/).
The proposed auth messages, bounds and reconciliation algorithm are project design recommendations,
not defaults supplied or guaranteed by those libraries.
