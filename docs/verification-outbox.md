# SCRUM-17 Outbox verification — 2026-11-01

Scope: Order-owned standalone worker, opt-in launch, no schema/API business change. The owner
requested continuation after the design handoff; defaults remain reviewable, not production SLOs.

| Check | Actual local result |
| --- | --- |
| Initial test-first run | Failed collection: worker module did not exist |
| Cleanup regression before fix | Failed: database cleanup had no deadline |
| Cleanup regression after fix | Passed: timeout becomes UnsafeShutdown, CLI termination path |
| Order `uv sync --frozen` | Passed (57 installed packages audited) |
| Order Ruff lint including explicit W, formatter and Mypy | Passed in final local check |
| Order non-integration pytest | 51 passed; 26 integration cases deselected |
| `python3 infra/run-service-integration.py` | 5 User + 14 Menu + 26 Order cases passed (45 total), real PostgreSQL and two real Kafka cases; Alembic upgrade/drift passed |
| Worker process | Real subprocess published to unique Kafka topic, excluded a contender and exited 0 after SIGTERM |
| ACK/mark recovery | Real broker ACK followed by injected restart before mark replayed identical ID/envelope, then version 2 |
| Default stack smoke | All 8 tests passed against existing local stack |
| Default/opt-in `docker compose config --quiet` | Both passed |
| Order Docker image / runtime schema | Final image build and runtime import/bundled-schema check passed |

Broker outage/latency is fault-injected; the shared broker was not stopped. No local application
topic or live pending order was published. The runner creates/drops only isolated databases and
UUID-named Kafka topics, not valuable volumes. Notification or browser delivery is not implemented.
CI results must be linked at their actual PR head; local green checks are not remote CI evidence.
No production deployment, PR merge, Kafka durability/load claim or real Telegram send occurred.

Known existing warning: Starlette TestClient/httpx deprecation. The independent Ruff PR #5 remains
open; this branch's local command explicitly enables W without silently merging that PR.
