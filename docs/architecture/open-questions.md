# Open decisions and assumptions

These are explicit follow-up decisions. Nothing in the placeholder UI answers them implicitly.

| Decision | Why it matters / when required |
| --- | --- |
| Staff lifecycle | Password accounts and operator provisioning selected/implemented in Stage 2; decide recovery, disabling, MFA, audit and immediate revocation before production |
| Production role lifecycle | Current role/action rules are implemented; decide account disabling, role change and revocation operations |
| Production JWT and internal auth | Stage 2 uses RS256, fixed issuer/audience/kid and 900-second tokens; finalize multi-key rotation, immediate revocation and internal service credentials |
| Slot scheduling | Capacity is orders and booking closes at start; ADMIN manages slots. Define cafeteria timezone, operating calendar, overlap policy and maximum advance window |
| Order numbering | Initial globally unique MAI sequence permits gaps; decide any later daily display convention |
| Menu snapshot validity | Five-second bounded snapshot and changed-total confirmation are implemented. Decide whether stricter version/reservation semantics are needed and design the frontend confirmation UX |
| Retention | Successful UUID-key idempotency records and events are retained indefinitely for now. Agree archival/retention and replay guarantees before cleanup |
| Telegram write permission | Choose bot start/deep-link or explicit write-access flow; define recipient association and blocked-bot behavior |
| Durable notifications | Select retry/deduplication persistence and recovery without assuming a relational DB; accept or mitigate duplicate-send crash windows |
| Event delivery | v1 payload and per-order version are fixed; decide topic retention, retry/quarantine topics, relay ordering, monitoring and replay expectations |
| WebSocket authentication | Decide credential transport, origin policy, role checks, token expiry, and race-safe REST reconciliation |
| Deployment | Select host, TLS termination, secrets, backups, monitoring, Kafka durability, and operational ownership before production rollout |
| Native Android | Staff MVP is adaptive web; native Android remains a future architectural option |

## Accepted bootstrap defaults

- Python 3.12, Node 22, five independent Python environments, npm workspaces for two apps.
- One local PostgreSQL instance with three databases and separate owners; one local Kafka KRaft node.
- NGINX reverse proxy; two static exports; local ports 8080 and 8081 by default.
- Stage 1 stopped at shells. Stage 2 adds User/Menu APIs; Stage 3 adds transactional orders, slot policies and persisted Outbox. Event delivery and real-time interfaces remain deferred.
- Domain/application directories are boundary markers, not implemented frameworks.
- All business prices are intended as integer kopecks; all stored times are timezone-aware.
- Russian placeholder interfaces and English engineering artifacts. Penpot is visual context only.
- Product Git publication to `KirillBelianskiy/mai-stolovka` was authorized on 2026-10-31. Existing `skills/` is preserved and ignored by the product repository.
- Load estimates are unverified; there is no production capacity or performance claim.

## Next development sequence

1. Agree relay ordering, topic/retry policy and durable notification state.
2. Implement Outbox relay and Notification delivery with failure/recovery tests and bot permission.
3. Implement authorized WebSocket delivery and REST reconciliation.
4. Integrate both frontends with existing User/Menu/Order contracts and explicit price confirmation.

Five-person ownership is suggested in the overview. A feature is not complete merely because its happy-path UI exists; its owning service must enforce its invariants and authorization.

## Current design review

Stages 4–6 are design-only under SCRUM-12. The [integration register](../stages/stages-4-6-design.md)
tracks historical peer READBACK and current sole-author reconciliation separately from owner approval
and implementation. Skill v0007 records the owner-authorized sequential takeover on 2026-11-01. Notification durable state,
recipient/permission and service-auth interfaces, stale READY policy, topic operations, WebSocket
auth/protocol and frontend credential/recovery choices remain proposal gates until explicitly resolved.

The consolidated D1–D10 decision register links each recommendation to its dependent implementation
tickets. Notification/frontend designs now exist as product PRs #6/#7; no departed-agent ACK is
required. Storage/service-auth, Telegram ambiguity and browser journal choices still need owner review.
