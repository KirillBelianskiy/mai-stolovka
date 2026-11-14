# Websocket Service

Owns the authenticated Kitchen WebSocket endpoint and Kafka-to-WebSocket invalidation hints.
See the root README and architecture documents for responsibilities and local infrastructure.

From this directory:

```sh
uv sync --frozen
uv run --frozen uvicorn websocket_service.main:create_app --factory --reload --port 8000
uv run --frozen ruff check .
uv run --frozen ruff format --check .
uv run --frozen mypy src
uv run --frozen pytest
```

The environment lives in this service's `.venv`; it is not the root PyCharm environment.
Set environment variables explicitly; `.env.example` is documentation and is not loaded automatically.
Choose another port when running several service processes on the host.

- `GET /health/live`: process availability and service identity.
- `GET /health/ready`: returns 503 until the consumer owns every topic partition and has
  initialized positions when Kafka consumption is enabled. Otherwise it reports process readiness.
- `WS /api/v1/ws/kitchen`: requires an exact allowed `Origin`, then a first frame
  `{"type":"auth","access_token":"<access token>"}` within five seconds. Tokens
  are verified with the configured RSA public key, issuer, audience, and key id;
  only `COOK`, `CASHIER`, and `ADMIN` roles are accepted. A `ready` message is
  queued before the connection joins fanout. The service sends only order id and
  version hints; clients reconcile current state through the Kitchen REST API.
- After authentication, clients send no application frames. Uvicorn sends a
  transport-level ping every 20 seconds and closes peers that fail to pong within
  20 seconds. Client application frames after auth are rejected.
- Configure `APP_ALLOWED_ORIGINS` as a comma-separated exact-origin allowlist.
  The default is for local development only. Authentication is fail-closed when
  no verification key is configured. Each connection has a bounded 128-message
  queue; overflow closes it with code `1013`. The ASGI server also caps frames at
  12 KiB.
- Close behavior: an absent or disallowed `Origin` is rejected during the
  handshake with HTTP 403; `4401` means missing, malformed, invalid, or expired
  auth and requires staff relogin; `4403` means an authenticated non-staff role;
  `1008` means an invalid or oversized frame; and `1013` means authentication
  configuration or the event stream is unavailable, or the connection queue overflowed. `1012` means
  the service is shutting down and the client should reconnect.

## Kafka and private Kitchen ingress

Set `APP_KITCHEN_KAFKA_ENABLED=true` for realtime deployments. The default is
`false` for existing local and test stacks. Provision `orders.events.v1` and run
the Order Outbox worker. Set `APP_KAFKA_BOOTSTRAP_SERVERS` to the internal broker
listener. `APP_KITCHEN_KAFKA_TOPIC` defaults to `orders.events.v1` and
`APP_KITCHEN_KAFKA_GROUP` defaults to `kitchen-orders-v1`. Use one WebSocket
instance per group and keep its group separate from Notification's.

The consumer uses the end of each partition for a new group and resumes a valid
committed offset on restart. It validates v1 events, fans out
`{"type":"order.changed","order_id":"<UUID>","version":2}` and commits the next
offset. A broker outage or rebalance suspends subscriptions. Transient broker
errors retry. An invalid event or out-of-retention committed position leaves the
consumer unready until the operator reconciles the Kafka stream or group and
restarts the service. Review the position and source data before recovery.
Client subscriptions resume with a fresh REST read.

Expose the exact same-origin WebSocket path on the private Kitchen listener with
upgrade forwarding and a read timeout of at least 60 seconds. Configure the
exact Kitchen page origin and the same JWT verification settings as staff REST.
Kitchen authenticates in the first frame, fetches the current role-filtered
queue on `ready`, and coalesces duplicate or older versions within a bounded
cache. Changes during a REST fetch trigger a follow-up fetch. Disconnects,
focus, visibility, network recovery and a 15-second visible poll also reconcile
through REST. The initial WebSocket handshake has a six-second REST fallback.
REST authorizes and executes every staff action.

Run the broker integration test with `KITCHEN_TEST_KAFKA` set to the address
of a disposable broker. It creates UUID-named topics and groups.
