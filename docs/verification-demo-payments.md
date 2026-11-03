# Demo wallet verification — MVP #32

Date: 2026-11-03. Branch: `codex/MVP-32-demo-wallet`, based on Outbox/topic operations
`07f02b62907e8b725b089dd4f822a1759b9da641` (#12, stacked on #8).
Owner approval: explicit confirmation of PR #34's Order-owned wallet, ADMIN Swagger credit,
checkout debit and allowed-cancellation refund. Skill v0012 records the bounded exception.
See [contract/runbook](architecture/demo-payments.md); Mini App payment remains #33.

## Acceptance defined before implementation

New tests were added before the wallet API/runtime: authorization/disabled-mode checks plus
credit replay/conflict, isolated balance reads, insufficient funds, concurrent checkout,
atomic rollback and repeated cancellation. The first focused run had **five real failures**:
POST `/wallet/credits` was absent and returned 404 instead of the required auth/disabled result.
The existing dynamic order GET already made anonymous GET `/wallet` return 401; that assertion
alone was not evidence of a missing wallet implementation. After implementation all five API
tests passed. No red integration run is claimed for tests not executed before runtime existed.

Additional cases then covered application restart, duplicate concurrent checkout, mixed
credit/cancel/checkout concurrency, credit-ledger fault rollback, immutable audit, free orders,
legacy cancellation and staff preparation/issuance. These are meaningful safety checks for
money-like demo state, not tests for documentation wording.

## Final local results

| Check | Observed result |
| --- | --- |
| Order `.venv/bin/python -m pytest -m 'not integration' -q --tb=short` | 62 passed, 51 integration cases deselected |
| `python3 infra/run-service-integration.py` | Real PostgreSQL: User 5, Menu 14, Order 51 passed; forward migrations and Alembic drift checks passed for all three; only UUID-named test databases created/dropped |
| Order Ruff including W, full format check, strict Mypy | Passed; 24 source files type checked |
| Root contract/topic unittest discovery | 15 passed; event v1 envelopes unchanged |
| Root Ruff including W | Passed |
| Order OpenAPI | Regenerated only `order-service.v1.json`; committed-snapshot comparison passes |
| Default and outbox-profile Compose configuration | Both validated without starting application services |
| Final Order container build | Passed using unchanged frozen dependencies |
| Built-image smoke | Prefixed Swagger HTML/schema, credit bearer security, disabled demo default, final migration syntax and Outbox import passed; no business request or migration run against application state |
| Test DB cleanup | PostgreSQL inventory returned zero `mai_test_%` databases after the runner |

The isolated runner also exercises the existing real Kafka Outbox/topic tests using disposable
topics/groups. It never launches the application Outbox profile or publishes pending application
orders. The test fixture now truncates the new demo tables only in the runner's isolated DB;
ledger UPDATE/DELETE is rejected while fixture TRUNCATE is deliberately available to its DB owner.

The tests demonstrate:

- Credit keys replay the original response; conflicting target/amount fails. Concurrent duplicate
  credit creates one audited addition. Invalid amounts/non-ADMIN/disabled requests are denied.
- Distinct concurrent checkouts cannot overdraw; duplicate concurrent checkout creates one debit,
  order, capacity reservation and event. Price/capacity failures do not move funds.
- Outbox insertion failure rolls back the debit/order/reservation, and cancellation event failure
  rolls back the refund/status/capacity. Credit ledger failure rolls back credit, wallet and key.
- Recreated app instances replay persisted credit and checkout responses without another write.
- Concurrent cancellation refunds once even after demo mode is disabled. Wrong owner/role/cutoff
  fails without a refund; ADMIN can cancel PREPARING; completed orders cannot refund.
- Legacy NOT_REQUIRED orders cannot mint refunds when demo mode is later enabled. Free orders
  have zero-value debit/refund evidence. Lifetime credit cap preserves integer refund headroom.
- Mixed operations reconcile wallet balance with ledger sum; normal UPDATE/DELETE of audit rows fails.

Existing Starlette/httpx TestClient deprecation warning remains. Dependencies were not upgraded.
Checks used existing service virtual environments; no claim of a fresh local frozen install.
Container build uses the unchanged frozen lock. Intermediate checks caught expected OpenAPI drift,
a payment-status typing mismatch and formatting/syntax errors; these were corrected before the
final passing runs. They are not represented as pre-implementation behavior red evidence.

## Limits and handoff

Exact PR-head CI is recorded in the PR handoff after publication; local tests alone do not
establish remote CI. No actual Telegram identity/bot send,
real customer, browser UI usability, payment provider, production rollout, backup restore or load
capacity is claimed. #27/#28/#29 retain integrated acceptance and operational/release gates.
The optional demo flag is not enabled in the checked-in defaults or the existing application DB.
No merge, deployment, destructive downgrade or live application migration was performed.
