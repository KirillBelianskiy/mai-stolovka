# Local backend test tunnel

This setup keeps both frontend apps on Cloudflare Pages and sends their API, health,
and kitchen WebSocket requests through Pages Functions to the fixed origin
`https://api-test.maistolovka.me`. Cloudflare Tunnel sends that hostname to the
local API-only NGINX listener on `127.0.0.1:8082`. The frontend origin, databases,
Kafka, and individual services are not tunnel origins.

## Isolated local stack

Use the approved integration checkout and a fresh Compose project name for each test
run. Pass the existing ignored environment file explicitly; do not copy it into this
checkout or print its contents. A unique project name creates separate Compose volumes.

```powershell
$project = 'mai-local-backend-tunnel-20261110'
$envFile = 'C:\MAI\5_sem\ITProject\Programs\mai-stolovka\.env'
docker compose --env-file $envFile -p $project --profile outbox --profile inbox config --quiet
docker compose --env-file $envFile -p $project up -d --build --wait --wait-timeout 300
docker compose --env-file $envFile -p $project exec user-service /app/.venv/bin/alembic upgrade head
docker compose --env-file $envFile -p $project exec menu-service /app/.venv/bin/alembic upgrade head
docker compose --env-file $envFile -p $project exec order-service /app/.venv/bin/alembic upgrade head
docker compose --env-file $envFile -p $project run --rm --no-deps --entrypoint /app/.venv/bin/alembic notification-service upgrade head
docker compose --env-file $envFile -p $project exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:29092 --create --if-not-exists --topic orders.events.v1 --partitions 1 --replication-factor 1 --config cleanup.policy=delete --config retention.ms=604800000 --config min.insync.replicas=1
docker compose --env-file $envFile -p $project --profile outbox --profile inbox up -d outbox-worker notification-inbox
docker compose --env-file $envFile -p $project ps
```

Postgres and Kafka remain bound to loopback. NGINX publishes the API-only listener
to loopback port 8082. Its server block includes only the existing explicit API,
health, and WebSocket route rules and returns 404 for every other path.

## Exact preview origins

Before testing a Pages preview, add its exact HTTPS origin (scheme and host, no path)
to `SESSION_COOKIE_ALLOWED_ORIGINS` and `WEBSOCKET_ALLOWED_ORIGINS` in the ignored
local environment file. Use the Mini App preview origin for sessions and the Kitchen
preview origin for WebSockets. Add each separately when the origins differ. Never
use `*`, a suffix match, or production origins in this test configuration. The User
Service checks the session Origin on login, restore, and logout; WebSocket Service
checks the handshake Origin. The Pages Functions do not enable credentialed CORS.

Pages requests stay same-origin. Each frontend Pages project needs the Functions
directory shipped with its static build. The proxy rewrites only the upstream
scheme/host to the fixed test hostname while retaining the incoming path, query,
request headers, body, cookies, Origin, response headers, and WebSocket handshake.
In particular, `Set-Cookie` remains on the same Pages origin, where the browser
stores the session cookie.

## Cloudflare setup boundary

Create a distinct remotely managed test tunnel in the Cloudflare account that owns
`maistolovka.me`, then publish `api-test.maistolovka.me` to
`http://127.0.0.1:8082`. Use a fresh credential for this tunnel and install it as
the Windows service. Never reuse a replica token from the production tunnel. Keep
the test hostname and Pages preview allowlists separate from production. Do not
change production DNS, Pages settings, tunnel routes, or the VPS.

The zone-owner Cloudflare session was unavailable during this task. Therefore no
Cloudflare resources were changed and no credential was created or installed.
Resolve that account access and rotate/revoke the previously exposed production
replica credential before attempting the tunnel setup.

## End-to-end acceptance

From both deployed Pages previews, confirm same-origin API reads, session login,
restore, and logout; rejection of a disallowed session and WebSocket Origin; and a
successful kitchen WebSocket upgrade. Check that `api-test.maistolovka.me` returns
404 for `/` and other non-API paths and does not expose either frontend, Postgres,
Kafka, or service ports. Restart the Windows cloudflared service and verify it
reconnects. These checks require the zone-owner account, reachable Docker Desktop,
cloudflared installation, and the Pages preview deployments. They are not local
unit-test substitutes.
