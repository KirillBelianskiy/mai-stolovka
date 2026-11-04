# MVP scope and pilot acceptance — issue #14

Status: partial owner decision, remaining choices proposed for review. Execution index:
[#13](https://github.com/KirillBelianskiy/mai-stolovka/issues/13). Target: the existing
https://maistolovka.me deployment. Owner: KirillBelianskiy; coordination: #10.

## Confirmed baseline and scope

The owner's continuation request authorizes work on the assigned backlog. It does not approve
every proposal in the design PRs. Stage 2 authentication and Stage 3 lifecycle remain implemented
baselines; later historical documents saying payment is deferred describe their original stage.

| Area | MVP scope / evidence state |
| --- | --- |
| Customer | Telegram-verified identity, menu/cart/profile, explicit total confirmation, slot booking, order ticket/history and allowed cancellation; #20/#21, not implemented end to end |
| Staff | Separate password accounts; COOK prepares, CASHIER issues, ADMIN manages menu/slots and allowed overrides; #22/#23 |
| Events | Order transactional Outbox and opt-in publisher #8; local topic/diagnostics #12. Durable Notification and staff hints remain #17/#18/#19/#24 |
| Payment | Owner explicitly included a demo balance and order payment on 2026-11-03: credit through API/Swagger is acceptable; no connection to a concrete payment provider. Not implemented in the inspected baseline. Backend/contract #32; Mini App #33 |
| Hosting | Existing maistolovka.me; API/WS/runtime assessment #25. Homepage availability does not prove complete journeys |
| Release | Isolated E2E #27 and operations #28 precede reviewed candidate #29 and controlled pilot #30 |

Provider integration, acquiring, bank transfers, real-money settlement, fiscal receipts and
production financial claims are outside this demo-payment decision. Payment tests use synthetic
credits. Any later real-money scope needs a separate decision and implementation review.
No provider credentials are needed for the agreed demonstration.

## Existing business invariants

The confirmed [lifecycle](../architecture/order-lifecycle.md) remains authoritative: one order
uses one slot-capacity unit; booking and permitted cancellation stop at slot start; CLIENT can
cancel only their own PENDING order; ADMIN can cancel PENDING/PREPARING before cutoff.
COOK/ADMIN advance PENDING → PREPARING → READY; CASHIER/ADMIN advance READY → COMPLETED.
Terminal orders cannot be reopened. Integer kopecks, server totals, expected versions and
stable per-user idempotency keys remain required. Payment adds no implicit permission to
change these rules. New payment transitions must be reviewed before runtime edits.

## Owner-approved demonstration payment scheme

The owner explicitly approved this scheme on 2026-11-03 after reviewing PR #34.
The decision is recorded in [the decision register](decision-register.md); backend implementation
is in [PR #36](https://github.com/KirillBelianskiy/mai-stolovka/pull/36).
Its transaction/security defaults and verification evidence are documented in that implementation.

- Keep a demo-only wallet/immutable ledger in Order Service's database, with no sixth service,
  new infrastructure or direct access to User/Menu databases. User UUID is an external reference.
- Provide an ADMIN-authorized credit API visible in Swagger, enabled only by an explicit demo
  setting. Require a positive bounded integer amount and an idempotency key; never a public
  arbitrary-balance setter. Label API/UI credits and payments as demonstrations.
- Debit the authenticated client's balance in the same transaction as order creation, capacity,
  idempotency and Outbox writes. Insufficient funds creates no order/reservation/debit. Payment at checkout is approved. A separately created unpaid order would require a new
  decision on expiry/reservation policy and extra states.
- A successful duplicate checkout replays the original result and never debits twice. Different
  concurrent checkouts serialize wallet access; no negative balances or lost updates. Establish
  and test a consistent wallet/order/slot lock order before implementation.
- Refund exactly once in the same transaction as an allowed cancellation. Disallow arbitrary
  staff refunds or balance edits until separately specified. Retain debit/refund/credit audit
  records and historical order snapshots.
- Keep order status semantics and v1 event envelopes stable where possible. Payment evidence
  belongs in an explicitly reviewed API/ledger contract; existing closed event schemas cannot
  silently gain fields. Do not make browser state the source of payment truth.

Track the backend/contract in [#32](https://github.com/KirillBelianskiy/mai-stolovka/issues/32)
and Mini App payment in [#33](https://github.com/KirillBelianskiy/mai-stolovka/issues/33),
both assigned to KirillBelianskiy. #27/#29 now depend on these payment acceptance results.
The backend implementation includes concurrent PostgreSQL tests, rollback injection and
contract/security checks; exact results are in PR #36. Mini App integration remains #33.
Swagger demo credit is an operator tool, not proof of bank settlement. Rollout approval does not
follow from a passing simulated payment.

## Acceptance scenarios

| ID | Scenario and required observation | Owning work |
| --- | --- | --- |
| A1 | Verified Telegram customer selects dishes/slot, accepts the server total and pays from a credited demo wallet. One order, debit, capacity allocation and creation event exist after repeated identical submissions; ticket says demo payment | #20/#21 plus payment work |
| A2 | Insufficient balance, changed price, full slot or cutoff rejects checkout without a debit, reservation or committed order; recovery never silently accepts a changed total | Payment work, #21/#27 |
| A3 | Owner cancels PENDING before cutoff; repeating cancellation restores capacity and demo balance once. Wrong owner/role, expired cutoff and terminal transitions fail | Payment work, #21/#27 |
| A4 | History/ticket reload shows authoritative current state and immutable accepted names/prices/payment evidence; expiry requires re-login and cannot expose another account's intent | #21/#27 |
| A5 | COOK finds the order, starts preparation and marks READY; customer notification is observed on an explicitly permitted test account. CASHIER issues it once; invalid roles and stale versions fail | #18/#22/#24/#27 |
| A6 | ADMIN changes a menu price/availability and manages unreferenced slots; non-ADMIN calls fail, referenced slots retain their lifecycle constraints | #23/#27 |
| A7 | Lost checkout response, broker/worker restart, missed staff hints and consumer replay recover without another debit/order or lost durable notification obligation; ambiguous Telegram delivery follows the agreed policy | Payment work, #17/#18/#24/#27 |
| A8 | Demo credit requires authorized operator access; duplicate credit adds funds once, invalid amounts fail, disabled demo mode refuses credit, and credentials/ledger data do not leak through logs | Payment work, #27/#28 |

These are acceptance requirements, not executed evidence. #27 must pin exact heads, environment,
test accounts and results. Existing local/API tests do not establish real Telegram entry or delivery.

## Pilot entry, exit and defect severity

Entry requires resolved applicable decisions, accepted implementation tasks including demo
payment, green candidate CI/E2E, observed auth/API/WS/bot paths, tested restore/rollback,
named operators, and explicit #29 rollout approval. #30 records participants, time window and
data/message permissions before any customer-facing exercise. Do not use real money.

Exit requires every A1–A8 scenario observed with evidence, all critical/high defects fixed and
retested, explicit accepted limitations and owner acceptance in #30. No throughput target or
usability claim is inferred from the demonstration; volume/recovery objectives remain decisions.

| Severity | Pilot rule |
| --- | --- |
| Critical | Unauthorized access, leaked credentials, cross-account data, duplicate/missing debit/refund, negative balance, duplicate order or corrupt capacity. Stop affected exercise; block release until fixed/retested |
| High | Core checkout/preparation/issuance unavailable, unrecoverable pending intent, lost notification obligation, or restore failure. Block acceptance until fixed/retested |
| Medium | Recoverable core-flow degradation with a documented workaround. Owner explicitly accepts or blocks it |
| Low | Cosmetic/non-blocking defect with no data or access impact; track owner and follow-up |

## Source and validation record

Inspected product main `4fb68861409fde88e6f0ea98d9cb7d7a61a79c4c`, Stage 2 authentication,
Stage 3 lifecycle, design-integration PR #4 at `5ffed86`, assigned issues #13–#30, and current
skill v0011. Payment inclusion and the exact Order-owned credit/checkout/refund scheme were explicitly
approved in the owner's chat replies on 2026-11-03. No provider or unrelated D2–D10 decision
is approved by those replies.
This change is documentation only: link/decision coverage and whitespace checks are recorded
in its PR; payment and end-to-end tests remain unexecuted until implementation.


## Persistent-login owner choice — 2026-11-04

The owner explicitly chose retained Mini App login after closing/reopening instead of the
memory-only mandatory-relogin recommendation. User-owned #40 now supplies the exact
protected session/restore/logout/security contract and runtime before #20 auth/profile and
#21/#33 integration. The UX choice does not approve cookie/CSRF/lifetime/rotation details
or change staff authentication policy. Public menu/cart proceeds independently in #41.

## Owner-confirmed checkout recovery and time display — 2026-11-04

The owner approved D9: account UUID, original checkout body and idempotency key in the current
tab's sessionStorage, without credentials/card data. Unknown outcomes reuse the original request;
clearing recovery data requires an explicit loss/duplicate-risk warning. Storage is untrusted and
does not prove identity, order existence or payment. Mac #21 owns the implementation.

The owner approved Europe/Moscow slot display with explicit МСК. This does not approve opening
hours/calendar, pilot fixtures, a 30-second freshness guarantee or other unresolved D10 choices.
Skill v0015 records the bounded exception; #33 payment UI and integrated #27 acceptance remain.
