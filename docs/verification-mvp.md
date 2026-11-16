# MVP acceptance — issue #27

Status on 2026-11-14: **Mac MVP acceptance preparation**. The local release harness exercises
the synthetic HTTP journey against the pinned application baseline. Integrated A1–A8 acceptance
awaits the reviewed candidate, staging handoff and controlled Telegram access.

## Run the local release acceptance entry point

From a clean candidate checkout with Python 3.12, OpenSSL and local Docker Compose:

```sh
python3 tests/e2e/mvp_acceptance.py --output /tmp/mai-accept-new-run.json
python3 -m unittest discover -s tests/e2e -v
```

Use a new report path outside the checkout. The entry point builds images from the checkout,
uses a UUID-named Compose project and fresh databases, generates signing keys and synthetic
identities, binds customer/staff HTTP to distinct loopback ports, runs preflight and the API
journey, and removes its project containers and volumes. It uses the local Docker context, a
private temporary environment and a generated synthetic Telegram signing key. The existing
workers and Telegram dispatch are outside this local exercise. Reports include sanitized
failures, application revision, running image IDs, migration heads, and observed synthetic
ledger, Outbox, status and slot state. A pass requires successful teardown. Built images may
remain in Docker's cache.

The API run exercises User login, ADMIN credit and fixtures, concurrent same-key checkout,
concurrent same-version cancellation, wrong-owner and role denial, and the COOK-to-CASHIER
handoff through the two proxy origins. The committed observations cover exactly-once local state and current order detail over REST. The full candidate gates below also require real browser/UI,
Telegram, staff network and worker/operations evidence.

See [release checklist](mvp/release-checklist.md) and [pilot evidence](mvp/pilot-results.md).

## Verified baseline results (2026-11-14)

Application base: `585f6147dc2c6fca6301d6e6339afd10f4991944` (`codex/ui-completeness`).
The [local report](acceptance/mac-local-2026-11-14.json) was generated at
`c1865e6ccfddc697b872996326c30e8dce803455` with Python 3.12.8, Docker 29.1.2 and Compose
2.40.3-desktop.1. The evidence-only descendant adds this report and its interpretation.

| Command or check | Observed result |
| --- | --- |
| `python3 tests/e2e/mvp_acceptance.py --output /tmp/mai-accept-c1865e6.json` | 11 stages passed, including 22 anonymous route checks and 52 authenticated or login requests. Both apps and all API images built. Four database migrations reached their recorded heads. |
| Concurrent checkout and cancellation | Two same-key checkout responses shared one order, original/replay flags and one 12,000-kopeck debit. Concurrent cancellation left one refund, one cancellation event, 50,000 kopecks and zero capacity used. After cancellation, replay returned the original response and GET returned CANCELLED v2. |
| Repricing and staff flow | Old total rejected, history retained 12,000 kopecks, then explicit 15,000-kopeck confirmation created the second order. COOK prepared and marked it READY. CASHIER completed it at version 4. Wrong roles, stale versions, terminal cancellation and full capacity were denied. Final wallet: 35,000 kopecks, one capacity unit used. |
| `python3 -m unittest discover -s tests/e2e -v` and `python3 -m unittest discover -s tests/contracts -q` | 2 harness regressions and 27 contract tests passed. Initial harness red was the missing module. |
| Order `python -m pytest -p no:cacheprovider tests/test_order_integration.py tests/test_wallet_integration.py -q --tb=no` and `python -m alembic check` | 39 passed and no schema drift on a temporary UTF-8 PostgreSQL 18.6 database, using existing dependencies and the pinned Order source. Covers slot cutoff, forced debit/refund/credit rollback, concurrent wallet operations and refund after disabling payments. The first run used a SQL_ASCII database and returned 24 failures; the corrected UTF-8 run passed. Existing Starlette/httpx deprecation warning. |
| `ruff check tests/e2e`, `ruff format --check tests/e2e`, `git diff --check` | Passed. |
| Docker cleanup | Verified no containers, volumes or networks with the completed acceptance project's label. |

## Reproduce the completed preflight

Use Python 3.12, no additional packages. Start an already provisioned isolated demonstration;
this script never starts containers, migrates, seeds, authenticates, places orders or sends messages.

```sh
python3 tests/e2e/mvp_preflight.py \
  --customer-origin http://localhost:8180 \
  --staff-origin http://localhost:8181 \
  --source-revision 87cf9e5989d248cae44aacdfedf708c820cb8411 \
  --output /tmp/mai-mvp-preflight-new-run.json
```

The output file must be new. Exit 0 means only that all route checks passed; 1 means at least
one failed; 2 means configuration/report creation failed. Loopback HTTP origins with explicit
ports are required. Launch URLs, credentials, nonlocal targets and redirects are rejected.
Requests are anonymous GETs, bounded to five seconds and 1 MiB. Reports record status/results,
not bodies, cookies, JWTs, initData or upstream exception text. No browser or credential store is read.

Per origin the eleven checks cover frontend HTML, five readiness identities, two public Menu
routes and 401 rejection for anonymous profile, order history and wallet access. Readiness of
Notification/WebSocket does not prove durable dispatch or event connectivity. Public Menu checks
establish response shape/availability, not correctness of menu data. HTTP preflight is not HTTPS,
Telegram, browser rendering, WebSocket authentication or real payment evidence.

The supplied source revision is an operator annotation, **not a verified deployment SHA**. Before
the full run, record actual candidate commit, container image IDs/digests, application/DB migration
versions and proxy configuration independently. Never infer running code identity from HTTP 200.

## Historical anonymous preflight evidence (2026-11-05)

The local-only integration `87cf9e5989d248cae44aacdfedf708c820cb8411` includes these inputs:

| Area | Review input |
| --- | --- |
| Mini App balance/payment | #50 `ff6497cde531ecc3dbd4681d7d36ef266c532e99`, stacked on #49 `0abc322c2a83868fa2daba0269b7ff3a26371d50` |
| Order wallet/runtime | #36 `7306674c4aaff16afaaa8c007bde5b714f3cb87f` |
| User sessions/recipient permissions | #46 `36a689709771cfc1938171e663e4a08d74dfa43f`; recipient block-report review findings remain unresolved |
| Kitchen/admin | #39 `0605d6604ef03aab5e76a147d55b33c7687ca893` |
| WebSocket foundation | #37 `2bdeb0a250869368846ae1dfa1b9a5156a0f9c4d`; Kafka/hint integration remains #24 |
| Notification inbox | #43 `e10599381941b181b928ab8fdcc8f4fac17467d3`; Telegram dispatcher remains #18 |
| Scope/owner decisions | #34 `098bff617a5d4cd10cba0b466bc5428e5c026994`; skill v0015 |

[Recorded preflight](acceptance/preflight-2026-11-05.json): 22/22 passed on local ports 8180/8181.
No authentication, database mutation, debit/refund, worker restart or Telegram delivery occurred.
The harness explicitly writes `journey_acceptance=not_run` and lists every unexecuted A1–A8 scenario.

Harness validation: actual initial red was the missing preflight module; six behavioral regression
tests then passed under Python 3.12. Ruff checks and formatting pass. Tests cover target validation,
redirect rejection, false-green prevention, wrong service identity, anonymous-access exposure and
sanitized transport failure reports. Those tests use controlled readers and are not live E2E evidence.

## Full-run start gate and fixture record

Before executing the matrix, assemble an explicitly accepted, disposable candidate containing
#18/#21/#23/#24/#25/#32/#33. Inspect #46 recipient fixes at the exact candidate head. Resolve
applicable notification ambiguity/intake, calendar and operational policies in #14; do not turn
proposed retry budgets or a display timezone into new business approval. Real Telegram launch and
delivery require the owner's explicit controlled-account/message permission. #29 rollout approval
and #30 pilot participants are separate from this isolated acceptance exercise.

Record the run ID/date, candidate SHA, image digests, configuration/migrations, timezone, fixture
UUIDs and roles, allowed test recipients, synthetic credit budget and executing operator. Use newly
provisioned CLIENT A/B, COOK, CASHIER and ADMIN accounts; initial balances and future slot capacity
must be known. Store credentials privately, outside committed evidence. Fixture menu/slots are
test data, not approved cafeteria hours. Keep browser, User/Menu/Order, worker and broker clocks
consistent. A dedicated stack must be identified before any mutation or restart.

For each step record observed request outcome, affected test IDs, server order version/status,
wallet/slot values, same-key response and an appropriately redacted screenshot/log reference.
Record DB/ledger counters through the owning service's approved verification mechanism; UI values
alone cannot prove exactly-once effects. Retain evidence until reviewed; tear down only that
disposable environment through its approved lifecycle, never the user's existing demo volumes.

## A1–A8 acceptance matrix

Full candidate execution of each row remains **NOT RUN**. Attach local API and service evidence
to the relevant rows when completing the remaining observations on the pinned candidate.

| ID | Reproducible actions | Required observations and evidence | Dependencies |
| --- | --- | --- | --- |
| A1 | Launch the controlled Telegram customer A. Record balance/slot count; select a dish/window, explicitly accept the server total, double-click checkout, replay the original UUID key/body, reload the ticket | One order, one debit/ledger entry, one capacity unit and one creation event; same order/key response; current ticket GET and Russian demo-payment label. Verify integer kopecks and authenticated ownership | #20/#21/#32/#33; #25 Telegram/HTTPS configuration |
| A2 | On separate known fixtures try zero balance, stale displayed balance, changed menu price, full slot and already-started slot. Confirm changed price in a separate action only after a definite rejection | Each rejection leaves order/debit/capacity unchanged. No silent total acceptance. Wallet refresh does not submit an order. Preserve original journal after an ambiguous outcome; definite insufficient funds offers an explicit retry after credit/refresh | #21/#32/#33 |
| A3 | A cancels its PENDING order before cutoff, repeats cancellation and reloads; B tries A's order; COOK/CASHIER attempt disallowed operations; test cutoff/READY/COMPLETED rejection on separate fixtures | Exactly one refund entry and capacity restoration; server `DEMO_REFUNDED`; no second refund; wrong owner/role denied; forbidden cancellation leaves balances/capacity/version unchanged. Keep actual HTTP codes and versions | #21/#22/#32/#33 |
| A4 | Reopen the Mini App, expire/refresh a short-lived test access token, switch A→B during a protected retry, revisit history/ticket and return to A's uncertain tab intent | Own-account history only; current REST state instead of original replay snapshot; no credentials in browser storage; original account/key/body recovery; foreign intent hidden and blocked; explicit clear-loss warning; accepted names/prices unchanged | #20/#21/#40/#33 |
| A5 | COOK opens A's order, starts preparation, marks READY; observe the permitted account's notification; CASHIER checks packaging and issues. Repeat/stale-version/invalid-role actions on fixtures | PENDING→PREPARING→READY→COMPLETED with expected versions; exactly one allowed issuance; actual controlled Telegram delivery/link evidence; no claim of exactly-once external sends beyond approved ambiguity policy | #18/#22/#24/#25 |
| A6 | ADMIN changes fixture price/availability; create/edit/delete an unreferenced fixture slot; attempt referenced-slot mutations and the same calls as CLIENT/COOK/CASHIER | Server authorization and lifecycle constraints hold; unavailable dish cannot be ordered; changed total requires confirmation; immutable historical order snapshots survive menu changes | #23/#21/#32 |
| A7 | Drop a successful checkout response, reload/relogin and replay the saved key/body; stop/restart only disposable broker/workers; disconnect/reconnect staff hints; test terminal-before-READY replay | One order/debit despite retry; current REST reconciliation; no lost durable notification obligation; offset/claim recovery evidence; late events cannot revive terminal work. Distinguish accepted ambiguous-send duplicates from new debit/order duplication | #17/#18/#21/#24/#32/#33; approved restart/ambiguity policy |
| A8 | ADMIN credits a fixture wallet with a UUID key; replay and concurrently repeat it; vary body under the same key; attempt invalid amounts and CLIENT/COOK/CASHIER credit; disable new demo payments in the disposable fixture, then cancel an already-paid eligible order | One credit, key/body conflict denied, strict bounded amounts and roles; disabled credit denied; existing paid cancellation still refunds once. Record forced transaction rollback and mixed credit/checkout/cancel concurrency from isolated PostgreSQL tests | #32/#27/#28 |

## Browser and failure evidence

Record browser/version/device for 390px mobile and staff tablet layouts. Traverse by keyboard as
well as pointer: slot selection, balance refresh, explicit repricing, retry, cancellation confirmation
and profile/account change. Inspect focus, labels, scrolling, wrapping and touch targets. A DOM test
or an HTTP response is not proof of layout or real Telegram behavior.

Apply the severity rules recorded in #14 or its reviewed scope handoff. A failed check records scenario, exact head/fixture,
steps, expected/actual, severity and owning issue. Stop an affected financial/security exercise for
duplicate/missing debit/refund, negative balance, cross-account access or corrupt capacity. Fixes
belong to the owning service/app branch. Retest on a newly pinned candidate; do not overwrite the
original failing evidence or close #27 while any required journey remains unobserved.

## Final Mac candidate gates

Pin the combined source SHA and the exact User, Kitchen, Notification and Mac Infra handoff heads
in the [release manifest](mvp/release-checklist.md). Run the local entry point on that checkout
and attach the new report. Use the candidate's approved staging routes and isolated fixture
record for the checks below. Each gate requires timestamp, observed result and evidence link.

| Gate | Procedure and pass criteria | Start dependency |
| --- | --- | --- |
| Real Telegram and User | After the coordinator supplies the approved candidate and separate test bot/account, launch from the real Telegram client over approved staging HTTPS. Sign in, close/reopen, exercise refresh and account isolation (A1/A4). Confirm secure session behavior and reject stale or invalid launch data using dedicated fixtures. Observe no credential values in artifacts. | User handoff and staging access from coordinator |
| READY and Telegram | Create separate eligible and ineligible synthetic recipients. Make orders READY as COOK, verify one durable obligation per event and recipient as specified, actual receipt and working ticket link for the eligible account, suppression for ineligible recipient and approved handling for blocked/revoked account. Correlate order/version, event ID, Kafka position and redacted dispatch outcome. CASHIER completes once. | Notification and User handoffs, approved test bot/account |
| Kafka, workers and WebSocket recovery | With the disposable broker/worker procedures, interrupt Kafka and each consuming/publishing worker with a pending synthetic order. Create or progress another order while hints are disconnected. Restore in the documented order. Compare Outbox publication, acknowledged offsets and durable inbox/retry state. Replay duplicate, delayed and terminal-before-READY events using the reviewed fixture procedure. Verify no skipped obligations, no resurrected terminal work and ambiguity handled under the approved send policy. Verify staff reconnect and REST reconciliation recover current order/version after lost, duplicate and delayed hints, and reject unauthenticated/client-role WebSocket connections. | Kitchen, Notification and Mac Infra handoffs |
| Remote staff and network switch | Use a real staff browser on the approved remote HTTPS origin from a device outside the Mac LAN. Check TLS, role-scoped access, REST and authenticated WSS. Start a COOK queue session on Wi-Fi, switch to mobile data while another operator changes a test order, then switch back. Repeat through CASHIER issuance. Record disconnection/recovery times, authentication and observed latest version, one issuance, and no stale queue revival. Verify unauthorized and expired sessions follow the documented denial or re-authentication path. | Kitchen and Mac Infra handoffs, remote test device/network |
| Restore and cutover rollback | Use the Mac Infra rehearsal and [release checklist](mvp/release-checklist.md). Verify a fresh restore and measured RPO/RTO, synthetic order/key/wallet/slot/Outbox/inbox/offset recovery, alerts and staff access. Rehearse candidate cutover and rollback to pinned prior artifacts, verify routing and re-run state/role invariants after rollback. Record approvals and evidence for the actual selected schema recovery route. | Mac Infra handoff and approved operational thresholds |
| Pilot and sign-off | Finish A1–A8 with pass/fail and linked evidence, record any blocker and retest at its exact candidate, and obtain approval under #29 before rollout. After authorized rollout, complete the #30 [pilot record](mvp/pilot-results.md). | Coordinator, operators and approved pilot cohort |
