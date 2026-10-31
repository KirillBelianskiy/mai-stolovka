# Stage 3 audit — SCRUM-11

Audit date: 2026-10-31. Owner: kirill_bel. Baseline: product main commit `4fb6886`.
[Follow-up issue](https://belianskiykirill-1793393094981.atlassian.net/browse/SCRUM-11).
Acceptance was recorded in Jira before the audit; SCRUM-8/9/10 remain completed implementation history.

## Source review

| Invariant | Reviewed implementation and supporting evidence | Outcome |
| --- | --- | --- |
| Capacity and booking cutoff | Creation locks the selected slot, checks server time and bounds, then increments in the order transaction; DB CHECK bounds the counter. Concurrent capacity test requests 10 orders for capacity 3. | No defect identified |
| Duplicate requests | User/key composite primary key claims with ON CONFLICT; canonical fingerprint covers sorted cart, slot and confirmed total. Matching committed requests replay their original body without Menu. Concurrent duplicates and conflicting payload tests cover the claim. | No defect identified |
| Authoritative totals/history | One available-dish batch snapshot precedes the locking transaction; client prices are forbidden. Strict integer bounds, confirmed-total conflict and snapshot age guards precede reservation. Stored names/prices remain immutable through lifecycle operations. | No defect identified |
| Roles and ownership | JWT verifier fixes algorithm/issuer/audience/key ID and required role claims. Only CLIENT creates; own reads hide other clients' orders. Staff transitions follow confirmed roles and expected versions. | No defect identified |
| Cancellation | Locks order then slot, refreshes slot state after lock, enforces owner/admin state/cutoff rules, and decrements once. Repeated and distinct concurrent cancellation regressions cover stale-counter/double-release risks. | No defect identified |
| Migrations/data ownership | Initial Order migration matches ORM tables, constraints, indexes and number sequence; only internal foreign keys. Explicit migrations, isolated upgrade and Alembic drift checks exist. | No defect identified |
| Atomic Outbox | Creation and each real mutation write one versioned event in the same transaction. Forced Outbox insert failure proves complete rollback. Persisted envelopes validate against the shared schema. No relay is claimed. | No defect identified |

The reviewed paths include Order application service, API dependencies/routers, JWT verifier,
Menu batch/client, ORM models and initial migration, integration runner and proxy routing.
No business-code, API, dependency or schema changes were warranted by this bounded review.
No new regression or fabricated red run is claimed for a documentation/governance audit.
This is an engineering review of the approved Stage 3 invariants, not a production security/load audit.

## Confirmed governance correction

The active generated skill still prohibited product commits/remotes/pushes after the owner explicitly
authorized publication. Its Git profile also claimed no remote existed. Additive skill v0005 updates
active context, roles and workflow while preserving earlier versions as history. It is registered
alongside Forge under the Codex user skill directory. Forge source and its nested Git stay unchanged.

Product audit branch: `SCRUM-11-stage3-audit`, based on current `origin/main`.
Skill audit branch: `SCRUM-11-stage3-audit-skill`, based on `origin/scrum-10-stage3-skill`.
Skill PR targets that branch, preserving open PR #2 → PR #1 → main. No histories are rewritten.

## Verification

[Baseline GitHub Actions run](https://github.com/KirillBelianskiy/mai-stolovka/actions/runs/41183811597)
passed all eight jobs: five backend matrix entries, frontend, contracts and integration. This
supersedes the historical pre-publication limitation in the original Stage 3 verification report.

Current audit local checks:

- Order Ruff/format/Mypy: passed.
- Order pytest: 33 passed; 18 DB cases explicitly skipped in that invocation.
- Event contract checks: 6 passed.
- Local DB/live-stack rerun initially could not connect because Docker Desktop was stopped.
  This is an environmental failure, not a passing test; final rerun evidence is recorded below.

The PR's GitHub workflow must pass at its published head before handoff. CI runs isolated real
PostgreSQL cases and disposable-stack smoke tests independently of the owner's bot credentials.
No PR merge, deployment or expansion into Kafka/notification/WebSocket/frontend delivery is included.

Final local rerun after starting Docker Desktop:

- `docker compose up -d --wait --wait-timeout 180`: passed; all ten containers healthy, no reset.
- `python3 infra/run-service-integration.py`: User 5, Menu 14, Order 18 passed (37 total);
  fresh-schema upgrades and Alembic drift checks passed for all three service databases.
- `python3 -m unittest discover -s tests/smoke -v`: 8 passed after proxy reload.
- Total cases rerun during this audit: 84 (33 Order units + 37 DB + 6 schema + 8 stack).
  The broader initial Stage 3 total of 154 is historical; it is not counted as a new local rerun.
- The established TestClient/httpx deprecation warning remains; no warning suppression was added.

Both Forge and the project skill were read before work. Forge inspected the product read-only.
Its generated-skill validator reports the known single failure, `Generated skill unexpectedly has
 a Git remote`. The owner explicitly authorized that remote; deleting it or modifying Forge to
silence the check would contradict the assignment. Separate skill metadata validation, active
version/reference checks, JSON profile parsing, unchanged prior-version checks, authorized origin,
private-cache exclusion and local-registration checks passed.
