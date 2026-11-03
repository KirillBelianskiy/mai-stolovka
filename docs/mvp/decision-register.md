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
| P2 Proposed | Order-owned demo wallet/ledger, atomic debit at checkout and exactly-once cancellation refund; ADMIN-only idempotent demo credit behind an explicit setting. Alternative: unpaid orders plus separate payment, requiring expiry/reservation policy | Owner reviews [scope proposal](scope.md#demonstration-payment-proposal); backend contract before migrations/API/UI. #21/#27/#29 depend on payment work |
| D1 Implemented for review | One PG-guarded opt-in worker, retained poison head and bounded ambiguous cleanup in #8. Not blanket production availability approval | #15 retains review/recovery requirements; owner accepts production tradeoffs under #28/#29 |
| D2 Proposed beyond development | Existing local one-partition/RF1/seven-day topic is development-only. Operator selects production replication/minISR/ACLs, retention, RPO/RTO and measured restore window; do not copy development values | Owner/operator via #15/#25/#28; #17/#24 recovery design depends on retained history |
| D3 Proposed | Independent notifications_db owner/inbox/obligations/quarantine with atomic durable responsibility before offsets. Alternative retry topics requires a different reviewed recovery design | Owner approves store/retention/backup; Bobr contract #16 and Mac #17/#18; shared provisioning needs one writer |
| D4 Proposed | User-owned trusted permission evidence, narrowly authenticated recipient lookup and observation intake in #26. Alternative service credentials/intake must preserve User ownership; no ADMIN impersonation or DB reads | Owner approves exact #26 API/auth/evidence/precedence; Bobr #16, then Mac #17/#18 |
| D5 Proposed | Local known-version READY eligibility; accept unseen-terminal/send race and no recall guarantee. Proposed eight attempts/24h, 10s request/60s lease with bounded ambiguous retries; alternative manual ambiguity repair reduces duplicate sends but delays delivery | Owner chooses duplicate-versus-delay behavior and budgets before #18; fake Bot API failure tests required |
| D6 Proposed | Choose trusted webhook with authenticated update receipt or single long-polling owner; name existing bot/entry flow without publishing token. Approve READY message/link, permission-denied UX and late-grant policy | Owner provides bot identity/configuration privately; Bobr #16/#25 and Mac #18/#20. Identity verification alone is not write consent |
| D7 Proposed | Staff first-frame JWT, exact Origin, queued ready/minimal hints; proposed 5s auth, 12KiB frame and 128 queue bounds. Alternative tickets/cookies requires backend contract work | Owner approves protocol/security tradeoffs; Bobr #19/#24, shared schema writer agreed first |
| D8 Proposed | Memory-only JWT with explicit re-login on expiry/reopen; preserve safe non-secret cart intent. Alternative durable sessions requires a new backend lifecycle | Owner accepts re-login UX before Mac #20 and Bobr #22; no unapproved token persistence |
| D9 Proposed | Account-bound validated sessionStorage checkout journal with original key/body; warn before clearing uncertain intent. Alternative memory-only loses recovery on close | Owner approves storage/privacy/recovery behavior before #21 and payment UI; never store credentials or trust a journal as payment proof |
| D10 Proposed | Visible 30s REST recovery plus focus/online reconciliation, eventual non-atomic pagination and explicit timezone display. Choose cafeteria timezone/calendar, opening days and pilot slot fixtures | Owner confirms calendar/timezone and freshness UX; Bobr #22/#23/#24 and Mac #21/#27 |
| P3 Proposed | Named pilot staff/customers, test window, synthetic-credit budget, alert/incident operator and accepted recovery objectives. Scope A1–A8 and severity rules proposed as acceptance baseline | Owner/operator #28/#30; entry requires #29 approval and no critical/high open defects |

## Readiness map

- Ready now: #14 decision/acceptance preparation; #15 runtime/design review; Bobr's #25
  read-only deployment assessment and #16 contract review. Respect exclusive paths.
- #20/#22 runtime waits for credential/entry decisions; #19 waits for protocol/security decisions.
- #17 waits for store and recipient decisions; #18 adds bot/retry/ambiguity decisions.
- Payment backend/UI waits for P2's reviewed transaction/security/API contract. Feature inclusion
  P1 is confirmed; it does not establish those implementation choices.
- #27/#28 require integrated implementations; #29/#30 retain rollout and participant permissions.

Do not mark #14 complete until the applicable decisions and acceptance matrix are approved.
Payment backend/contract is tracked in #32 and Mini App payment in #33, assigned to
KirillBelianskiy. #27/#29 require both payment acceptance results; the original sixteen-task
plan alone no longer describes the complete MVP.
