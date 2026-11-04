# MVP decisions — issue #14

Status terms: confirmed (explicit owner decision), implemented (existing verified baseline),
proposed (concrete option awaiting decision), blocked (dependent work cannot start).
PR creation, assignment, CI and peer readback do not turn proposals into owner decisions.
Decision authority is the project owner; assigned implementers prepare contracts and evidence.
Record decision date and source beside each row when resolved; preserve prior decisions.

The D1–D10 IDs refer to [design integration #4](https://github.com/KirillBelianskiy/mai-stolovka/pull/4)
at `5ffed86`; they are not new Jira issue numbers.

| ID / status | Concrete options / recommendation for review | Dependencies and next owner action |
| --- | --- | --- |
| P1 Confirmed, 2026-11-03 | Demo balance, credit through API/Swagger and payment are included; no concrete payment-provider connection. Source: owner's direct chat reply during #14 work | Track backend and UI payment work before #27/#29; not implemented |
| P2 Confirmed, 2026-11-03 | Order-owned demo wallet/ledger, atomic debit at checkout, exactly-once allowed-cancellation refund and ADMIN-only idempotent Swagger credit behind an explicit demo setting. Owner replied “Да, реализовать эту схему” to this exact proposal | Backend #32 implemented for review in #36; API/transaction/security details and evidence are in its product docs. Mini App #33 remains pending; #21/#27/#29 depend on integration |
| D1 Implemented for review | One PG-guarded opt-in worker, retained poison head and bounded ambiguous cleanup in #8. Not blanket production availability approval | #15 retains review/recovery requirements; owner accepts production tradeoffs under #28/#29 |
| D2 Proposed beyond development | Existing local one-partition/RF1/seven-day topic is development-only. Operator selects production replication/minISR/ACLs, retention, RPO/RTO and measured restore window; do not copy development values | Owner/operator via #15/#25/#28; #17/#24 recovery design depends on retained history |
| D3 Proposed | Independent notifications_db owner/inbox/obligations/quarantine with atomic durable responsibility before offsets. Alternative retry topics requires a different reviewed recovery design | Owner approves store/retention/backup; Bobr contract #16 and Mac #17/#18; shared provisioning needs one writer |
| D4 Proposed | User-owned trusted permission evidence, narrowly authenticated recipient lookup and observation intake in #26. Alternative service credentials/intake must preserve User ownership; no ADMIN impersonation or DB reads | Owner approves exact #26 API/auth/evidence/precedence; Bobr #16, then Mac #17/#18 |
| D5 Proposed | Local known-version READY eligibility; accept unseen-terminal/send race and no recall guarantee. Proposed eight attempts/24h, 10s request/60s lease with bounded ambiguous retries; alternative manual ambiguity repair reduces duplicate sends but delays delivery | Owner chooses duplicate-versus-delay behavior and budgets before #18; fake Bot API failure tests required |
| D6 Proposed | Choose trusted webhook with authenticated update receipt or single long-polling owner; name existing bot/entry flow without publishing token. Approve READY message/link, permission-denied UX and late-grant policy | Owner provides bot identity/configuration privately; Bobr #16/#25 and Mac #18/#20. Identity verification alone is not write consent |
| D7 Proposed | Staff first-frame JWT, exact Origin, queued ready/minimal hints; proposed 5s auth, 12KiB frame and 128 queue bounds. Alternative tickets/cookies requires backend contract work | Owner approves protocol/security tradeoffs; Bobr #19/#24, shared schema writer agreed first |
| D8 UX confirmed, 2026-11-04; security contract pending | Owner chose retained Mini App login after close/reopen: “Нужен вход с сохранением сессии”. The memory-only/mandatory-relogin recommendation is rejected for customers. A User-owned protected persistent session/restore/logout contract is required; do not persist JWT/initData in browser storage | Bobr #40 specifies and implements the exact cookie/CSRF/lifetime/rotation/recovery boundary; Mac #20 auth/profile and #21/#33 depend on it. Staff-session policy is unchanged; public menu/cart proceeds independently in #41 |
| D9 Confirmed, 2026-11-04 | Owner approved an account-bound validated sessionStorage checkout journal in the current tab, original key/body retained for unknown outcomes and explicit warning before clearing recovery data: “Да, хранить в текущей вкладке”. No credentials or card data; storage is never identity/order/payment proof | Mac #21 implements within the approved tab scope. Closing/clearing can lose recovery; new price confirmation cannot silently replace an uncertain request. #33 remains a separate payment UI unit |
| D10 Display timezone confirmed, 2026-11-04; other choices pending | Owner approved Europe/Moscow slot display with explicit МСК: “Да, Москва / МСК”. Opening hours/calendar, pilot fixtures and a proposed 30s freshness policy are not approved by this display choice | Mac #21 uses explicit current-status REST recovery without claiming an approved SLO. Bobr #22/#23/#24 and Mac #27 retain calendar/freshness/operational gates |
| P3 Proposed | Named pilot staff/customers, test window, synthetic-credit budget, alert/incident operator and accepted recovery objectives. Scope A1–A8 and severity rules proposed as acceptance baseline | Owner/operator #28/#30; entry requires #29 approval and no critical/high open defects |

## Readiness map

- Ready now: #14 decision/acceptance preparation; #15 runtime/design review; Bobr's #25
  read-only deployment assessment and #16 contract review. Respect exclusive paths.
- #20 public menu/cart is implemented for review in #41; customer auth/profile waits for
  User-owned persistent-session task #40 and the actual entry contract. #22 retains its own
  staff credential decisions; #19 retains protocol/security gates.
- #17 waits for store and recipient decisions; #18 adds bot/retry/ambiguity decisions.
- Payment P1/P2 are confirmed; backend #32 is implemented for review in #36. Mini App #33
  follows that API and the remaining applicable browser/checkout decisions. Other D2–D10
  proposals are not approved by the payment decision.
- #27/#28 require integrated implementations; #29/#30 retain rollout and participant permissions.

Do not mark #14 complete until the applicable decisions and acceptance matrix are approved.
Payment backend/contract is tracked in #32 and Mini App payment in #33, assigned to
KirillBelianskiy. #27/#29 require both payment acceptance results; the original sixteen-task
plan alone no longer describes the complete MVP.
