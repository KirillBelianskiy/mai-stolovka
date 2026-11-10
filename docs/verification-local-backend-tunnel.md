# Local backend test tunnel verification

Baseline: `a9b693e6633f36b582545b86986d3e59b11b884a` on
`integration/agents-2026-11-08`. Task branch: `infra/local-backend-tunnel-test`.

## Results

| Check | Result |
| --- | --- |
| Docker Compose configuration and isolated stack | `config --quiet` passed; all services were built and started with both profiles and fresh project volumes. One-shot inbox exited before migrations on the first startup and was recreated after migrations. |
| Explicit Alembic migrations and service readiness | User, Menu, Order, and Notification `alembic upgrade head` each exited 0. The documented one-partition `orders.events.v1` dev topic was provisioned only in the isolated broker. Core services, Postgres, Kafka, proxy, both frontends, outbox worker, and inbox worker were running; all HTTP service readiness paths returned 200. |
| API-only NGINX route exposure on loopback | NGINX config syntax passed; listener observed on `127.0.0.1:8082`; API menu categories returned 200, `/` and a UI static path returned 404. Compose published Postgres, Kafka, and NGINX ports on `127.0.0.1`. |
| Pages Functions API/session/WebSocket proxy | Both proxy unit suites passed (2 tests each). Docker frontend build ran Telegram unit/component tests (32 + 14 passed) and production build/typecheck for both apps. Pages preview end-to-end checks require a preview deployment. |
| Cloudflare test tunnel, hostname, and Windows service | Blocked: connected Cloudflare account is `3ca9de270abf11764077c8b92f7a4faf`; zone owner account `a0d73327919b73d3a624b75ff1be12ef` is unavailable. Official cloudflared 2026.10.7 is installed, but no test tunnel credential or Windows service was configured. No Cloudflare mutation was made. |
| Frontend typecheck/build and relevant service checks | Both Docker frontend builds passed including Next.js TypeScript checks using the repository's Node 22 image. Host `npm ci` was attempted with Node 24.14.0, outside the repository's Node 22 range; npm exited with an internal `Exit handler never called` error. A direct host pytest attempt stopped at missing `asyncpg`; service tests were not rerun outside the Docker production images. |

The existing ignored environment file was not printed, copied, or committed. No
production routes, DNS, Pages settings, VPS, or tunnel were changed. No Telegram
validation or messages are claimed.

## Commands

| Command | Result |
| --- | --- |
| `docker compose --env-file <existing ignored env> -p mai-local-backend-tunnel-20261110 --profile outbox --profile inbox config --quiet` | Passed (exit 0). |
| `docker compose --env-file <existing ignored env> -p mai-local-backend-tunnel-20261110 --profile outbox --profile inbox up -d --build --wait --wait-timeout 300` | Built all images and started core services. First wait exited 1 because fresh-database workers correctly fail closed without their schema/topic. After migrations and explicit topic setup, `up -d --force-recreate notification-inbox outbox-worker` left both workers running and core services healthy. |
| Explicit User, Menu, Order, and Notification Alembic migrations | All four commands passed (exit 0). Notification used the documented `docker compose run --rm --no-deps --entrypoint /app/.venv/bin/alembic notification-service upgrade head`. |
| Create local `orders.events.v1` topic with one partition, one replica, and documented retention settings | Passed (exit 0) in the isolated broker; no external Kafka topic was touched. |
| `node --experimental-strip-types --test tests/pages-proxy.test.mjs` in each frontend workspace | Telegram 2/2 passed; Kitchen 2/2 passed. |
| `docker compose ... up -d --build --wait --wait-timeout 300` frontend build stages | Both Next.js builds and TypeScript checks passed; Telegram unit tests 32/32 and component tests 14/14 passed. |
| `docker compose ... exec -T proxy nginx -t` | Passed. |
| API-only listener and health probes | `GET /api/v1/menu/categories` and all five `/health/{user,menu,order,notification,websocket}/ready` paths on port 8082 returned 200; `/` and `/_next/static/test.js` returned 404. Compose published the listener as `127.0.0.1:8082`. |
| Pages preview session, exact-Origin, API, and WebSocket checks | Not run: no preview deployment or zone-owner access. |
| Host `npm ci` | Failed with npm internal `Exit handler never called`; runtime was Node 24.14.0 while repo requires Node 22. Docker frontend build used Node 22 and completed. |
| Host service pytest invocation | Failed during User Service `conftest.py` import: `ModuleNotFoundError: No module named 'asyncpg'`; no host service test suite completed. |
| `cloudflared --version` | 2026.10.7 installed from the official Cloudflare WinGet package. No service/tunnel credential was configured. |
