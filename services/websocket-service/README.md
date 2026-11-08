# Websocket Service

Owns the authenticated kitchen WebSocket endpoint and process-local fanout boundary.
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
- `GET /health/ready`: process only; Kafka/Telegram integrations are not started.
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
  configuration is unavailable or the connection queue overflowed. `1012` means
  the service is shutting down and the client should reconnect.

Kafka event consumption and REST reconciliation integration are implemented in
the dependent SCRUM-20 task. The fanout hub is process-local and is not a durable
event store; order state remains authoritative in the Kitchen REST API.
