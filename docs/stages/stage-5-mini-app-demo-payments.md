# Mini App demo-payment integration — MVP #33

Implemented for review on `codex/MVP-33-mini-app-demo-payments`, stacked on checkout PR #49 at
`0abc322c2a83868fa2daba0269b7ff3a26371d50`. Order runtime dependency: PR #36 at `7306674`.
Scope is Mini App UI/adapters/tests; backend and shared contracts remain unchanged.

## Behavior

Checkout reads the authenticated account's `/api/v1/orders/wallet`, validates the account UUID,
strict integer kopecks, RUB, synthetic-funds marker and boolean checkout mode. Russian UI labels
the balance as demonstration funds, explains ADMIN API/Swagger credit and shows whether checkout
currently requires payment. There is no customer top-up control or browser balance persistence.

New checkout is disabled while the wallet is pending, refreshing or unavailable. A low observed
balance is a warning; Order remains the authority for atomic affordability and total checks.
Refresh never initiates checkout. Definite insufficient-funds rejection displays recovery guidance;
unknown outcomes retain the original account-bound tab intent and key/body. Recovery remains
available even if the current balance cannot be fetched: a paid order may already exist.

Wallet data is account-keyed in the existing own-order cache and refreshed on focus/reconnect and
after checkout attempts/cancellation. No optimistic debit/refund arithmetic is performed. Existing
account-generation checks and cache cleanup are preserved.

History and ticket display only the server's `payment_status`: `NOT_REQUIRED`, `DEMO_PAID`,
`DEMO_REFUNDED`. Omitted historical replay evidence is shown as unknown, never fabricated as paid
or unpaid. Refunded evidence requires a cancelled order. Current ticket GET remains independent
of the original idempotency snapshot. Allowed cancellation uses the existing expected version;
the UI reports a refund only after server evidence and offers no second cancellation for a
cancelled order. Displayed wallet/order data is explicitly a last-read snapshot, not a guarantee
of current funds or settlement.

## Verification — 5 November 2026

- Actual red: new payment adapter test failed because `loadWallet` did not exist. Green: all
  30 Node API/domain tests passed, including own-wallet validation and payment-evidence decoding.
- All 14 DOM component tests passed, including server-paid/refunded display, balance outage and
  refresh, insufficient funds without automatic POST retry, and lost-success response recovery
  with the same key/body while wallet reads fail. Existing repricing, account switch, cancellation
  conflict and journal tests remain green. These use controlled API fixtures, not a real ledger.
- Both workspace typechecks and static production builds passed with Node 22.22.2 and locked
  Next.js 16.4.3. The default host Node 22.14 initially could not start jsdom/undici; no tests ran in
  that attempt. Using the already installed compatible Node fixed the environment.
- Live read-only adapter acceptance against the running isolated `mai-food-demo` backend validated
  an actual own-wallet response and four history orders containing `DEMO_PAID`/`DEMO_REFUNDED`.
  A synthetic local login was used and revoked afterward. No credit/order/cancellation was sent.
- `git diff --check` passed. No runtime dependency or lockfile change.

Full mobile browser/touch/keyboard visual acceptance, live debit/refund/restart/lost-response E2E,
real Telegram/HTTPS entry and cross-service candidate acceptance remain #27. Component tests do
not establish those results. #33 stays open for independent review/integrated acceptance.

Design retains the existing ivory/navy/blue cafeteria UI and ticket motif; the wallet is a compact
informational panel within checkout with a 44px minimum refresh target and wrapping heading.
No new inspiration source or framework was introduced.

Technical reference checked 2026-11-05: [TanStack Query important defaults](https://tanstack.com/query/latest/docs/framework/react/guides/important-defaults).
Account-keyed queries use stale revalidation, focus/reconnect refresh and explicit invalidation;
these mechanisms do not provide a financial freshness guarantee.
