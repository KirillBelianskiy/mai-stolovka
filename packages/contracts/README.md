# Shared contracts

This directory contains language-neutral wire contracts, not shared ORM models or business logic.

- `events/envelope-v1.schema.json`: JSON Schema 2020-12 event envelope and Order payload contracts.
- `events/examples/`: illustrative examples validated against the finalized v1 producer schema.
- `openapi/{user,menu,order}-service.v1.json`: Current exported API contracts; regenerate using
  `python3 infra/export-api-contracts.py` after an intentional API change. Service tests detect drift.

Validate examples with `uv run --frozen python -m unittest discover -s tests/contracts -v`
from the repository root after `uv sync --frozen`. Format validation is explicitly enabled.

Review changes with the producer and all affected consumers. Follow the versioning and delivery
rules in `docs/architecture/events.md` before implementing event processing.
