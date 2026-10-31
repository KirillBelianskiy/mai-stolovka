# Data ownership

Status: User/Menu/Order entities and migrations are implemented through Stage 3. Consumer storage remains undecided.

| Owner | Database / login role | Owned data |
| --- | --- | --- |
| User Service | users_db / users_owner | UUID user ID, unique nullable Telegram ID, nullable username, full name, role, creation timestamp; separate staff_credentials with unique normalized login and Argon2 hash |
| Menu Service | menu_db / menu_owner | Categories and menu items, integer prices in kopecks, image URLs, availability |
| Order Service | orders_db / orders_owner | Slots, orders, immutable item snapshots, idempotency records, outbox |
| Notification Service | No relational database in Stage 1 | Durable retry/deduplication storage remains a prerequisite before delivery implementation |
| WebSocket Service | No database | Ephemeral connections; canonical order state remains in Order Service |

Service UUID references are not PostgreSQL foreign keys across databases. Within a database, normal foreign keys and constraints should enforce integrity. Services must not import another service's ORM models, application classes, or repositories. `packages/contracts` contains wire contracts only.

The menu owns the current price. Orders own historical `price_at_moment` and `name_at_moment`; later menu changes must not rewrite order history. Store money as integer kopecks, quantities as positive integers, and timestamps as timezone-aware UTC values. Display in the relevant local timezone; the cafeteria's operational timezone needs confirmation before slot scheduling.

## Current and future interactions

- Client authentication and profile operations go to User Service.
- Menu browsing and menu administration go to Menu Service.
- Order Service requests an authoritative menu snapshot by internal REST before opening its locking transaction. No client-supplied price or name is authoritative.
- Order creation, order lookup, and status changes remain in Order Service. Employee WebSocket events tell clients to reconcile with this REST source.
- Domain events may carry the minimal data required by consumers; do not include Telegram initData, JWTs, bot tokens, or complete user profiles. How Notification Service obtains a permitted recipient remains an open contract.

No distributed database transaction or synchronous cross-service call under a slot row lock is planned. Stage 3 bounds a snapshot to five seconds at slot-lock acquisition; a changed total returns a confirmation conflict. There is no distributed lock on Menu availability. See order-lifecycle.md for that consistency boundary.

## Local database isolation

The PostgreSQL initialization script creates separate login owners without superuser, role creation, or database creation privileges. It revokes PUBLIC privileges on the three application databases and PUBLIC connection access to the default databases. Each owner can connect to its own database and own its schema; other application roles cannot connect. The bootstrap administrator is used only for database initialization/operations, never by a service.

One login also performs migrations in local development. Separate migration/runtime credentials may be introduced when deployment requirements justify them. Schema grants and DB ownership follow [PostgreSQL privilege rules](https://www.postgresql.org/docs/current/ddl-priv.html).

Init scripts execute only when the PostgreSQL data volume is empty. Changing `.env` passwords does not rotate credentials in an existing volume. Rotate them explicitly through PostgreSQL; never delete data merely to apply a password change outside disposable development environments.

The smoke suite checks successful own-database connections, rejected cross-database connections, role flags, database owners, Kafka readiness, and Alembic execution. A configured role name alone is not evidence of isolation.
