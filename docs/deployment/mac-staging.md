# MAI Food local staging on Mac

Use a dedicated worktree on the Mac and an already installed Docker Desktop with Compose 2.24.4 or later. The host build uses Python 3.12, OpenSSL, Git, and Node.js 22 with npm. The tested starting point is frontend commit `585f6147dc2c6fca6301d6e6339afd10f4991944` (PR #58).

## Start and verify

Run from the root of the staging worktree.

```sh
python3 infra/mac-staging.py init
python3 infra/mac-staging.py build
python3 infra/mac-staging.py up
python3 infra/mac-staging/smoke.py
```

Run `init` once. It creates staging-only database passwords, JWT keys and a synthetic bot token in `.private/mac-staging/staging.env`. The smoke test writes synthetic customer and staff rows to the staging database. Its staff credentials are randomly generated. The baseline build runs both Next.js static exports and the Mini App tests against the committed npm lockfile. Backend builds use the staging worktree source.

| Listener | Local URL | Routes |
| --- | --- | --- |
| Customer | <http://localhost:18280/> | Mini App, menu reads, Telegram session endpoints, customer profile, slots, wallet balance and own orders |
| Kitchen | <http://localhost:18281/> | Kitchen export, staff sign-in, menu and slot management, staff orders, demo credit endpoint and Kitchen WebSocket |

Only Caddy is published, on these two IPv4 loopback ports. Databases, Kafka, workers, role verification and service ports stay inside the Compose project `mai-food-mac-staging`. Use a single running copy per Mac. The script uses a dedicated env file and ignores shell Compose setting overrides. The operator can provision a synthetic staff account with the existing User CLI.

```sh
docker --context desktop-linux compose -p mai-food-mac-staging \
  --env-file .private/mac-staging/staging.env \
  -f docker-compose.yml -f compose.mac-staging.yml exec user-service \
  /app/.venv/bin/python -m user_service.cli provision-staff \
  --username staging-admin --full-name "Staging Admin" --role ADMIN
```

To open the Mini App as a synthetic customer in a browser, generate a short-lived launch URL from the staging token.

```sh
PYTHONPATH=infra/mac-staging python3 - <<'PY'
from pathlib import Path
from urllib.parse import urlencode
from smoke import identity

lines = Path(".private/mac-staging/staging.env").read_text().splitlines()
token = next(line.partition("=")[2] for line in lines if line.startswith("TELEGRAM_BOT_TOKEN="))
if not token.startswith("local-staging:"):
    raise SystemExit("A synthetic staging token is required")
print("http://localhost:18280/#" + urlencode({"tgWebAppData": identity(token)["init_data"]}))
PY
```

The script provisions `orders.events.v1` and starts Outbox and Notification Inbox. The
standalone #62 baseline uses Kitchen REST polling and keeps fake dispatch off.

## Run the combined release locally

Use a dedicated worktree containing the wiring change plus Kitchen [#63](https://github.com/KirillBelianskiy/mai-stolovka/pull/63)
at `dd372a14a3676e221e7b7d2f5ef6fb44c5ddedc5` and Notification
[#64](https://github.com/KirillBelianskiy/mai-stolovka/pull/64) at
`e72ee6d4e2fc06774feaf18a253c821d1ef679e2`. Pin the combined revision before building.

```sh
export MAI_STAGING_INSTANCE=release
python3 infra/mac-staging.py init
python3 infra/mac-staging.py build FULL_COMBINED_COMMIT_SHA
```

The release instance uses `mai-food-mac-staging-release`, separate volumes and ignored files
under `.private/mac-staging-release/`. It publishes customer at <http://localhost:18480/>
and Kitchen at <http://localhost:18481/>, alongside the baseline on 18280/18281. Reserve one
release instance per Mac. The baseline commands remain available with
`MAI_STAGING_INSTANCE=baseline`.

In `.private/mac-staging-release/staging.env`, set `STAGING_KITCHEN_KAFKA_ENABLED=true`
to enable Kitchen hints, and `STAGING_DISPATCH_FAKE_ENABLED=true` to enable READY dispatch
to the bundled fake Bot API. Leave `TELEGRAM_BOT_TOKEN` set to its generated synthetic value.
Both features default to off, and the release initializer creates a dedicated Notification
signing pair. User gets the matching public key. The worker receives the private key and uses
the internal User origin with the services' default issuer, audience and key ID.

```sh
python3 infra/mac-staging.py up
python3 infra/mac-staging.py status
python3 infra/mac-staging/smoke.py
node --test apps/kitchen-app/tests/realtime.test.mjs
```

Startup migrates Notification through `0002_ready_dispatch` on the combined checkout before
starting one `python -m notification_service.dispatch` worker. The worker health check verifies
configuration and migration readiness. The worker and fake API have no published ports. The
fake API accepts synthetic send requests and logs an aggregate count without logging recipient
IDs or message bodies. To disable it, clear the opt-in flag to `false` and rerun `up`, or run
`down` to stop the release. Leave the migration and delivery history in place.

Kitchen consumes `orders.events.v1` from `kafka:29092` as one replica in
`kitchen-orders-v1`. Readiness returns 503 until partition assignment and on Kafka failure.
Check logs before restarting after a retention gap or malformed record. Preserve Kafka offsets
and data while diagnosing. Caddy preserves WebSocket upgrades and has no configured upstream
stream timeout.

## Routes and operations

The customer allowlist is based on #59 at `4963b19ed89aa9de90741f3d6670f08fe915211f`. Caddy strips inbound forwarding and marker headers. Its internal guard uses User Service's existing JWT verifier to require a signed client token on shared profile and Order routes, and Caddy sets `X-MAI-Public-API: 1` on those requests for the marker-aware User release. The staging gateway enforces the same role restriction on Order at the gateway. The downstream services still enforce endpoint permissions and ownership. The private Kitchen route receives no public marker.

The webhook is disabled on a fresh install. For a local synthetic smoke check, set `STAGING_WEBHOOK_ENABLED=true` and set `TELEGRAM_WEBHOOK_SECRET` to a random value from `openssl rand -hex 32`. Run `up` and the smoke script, then restore the flag to `false` and run `up` again. The only published webhook route is exact POST `/api/v1/users/internal/v1/telegram/webhook`. User Service validates the secret and database-backed update replay receipts. This local check needs no Telegram registration.

Use `python3 infra/mac-staging.py status` to inspect this project and `python3 infra/mac-staging.py down` to stop it while preserving data. For logs, use the same Docker context, project, env file, and Compose files as the provisioning command above. Check worker status and logs after starting them since they have no readiness probe.

`build FULL_COMMIT_SHA` builds and selects both exports from a clean snapshot. Failed builds leave the current release selected. `select FULL_COMMIT_SHA` rolls back to a previously built pair by replacing the shared symlink in one operation. A browser tab loaded before a switch should reload to use the new release. Static rollback does not reverse server migrations. Keep the backend checkout and selected frontend commit compatible.

## Outbound transport candidates for a later staging session

Keep the two local listeners as the origin interface. Managed TLS belongs at the connector edge. Set the two `STAGING_*_ORIGIN` values to the exact browser origins for User's cookie check and WebSocket Origin validation. Select transport and DNS only when public staging is authorized.

**Pangolin Cloud Basic.** Use a Pangolin Site with the Newt macOS ARM64 binary running from a staging directory in the foreground. Pangolin documents Basic custom domains, 5 users, 5 sites, 5 domains, 15 public and 15 private resources. The terms reserve the free tier for non-commercial use. Confirm eligibility before using it for MAI Food, and confirm any dashboard traffic limits for the account. The domain docs reserve provider names such as `.hostlocal.app` and `.tunneled.to` for paid plans. Use an authorized staging hostname and add the CNAME value shown by the dashboard. For a separate staging apex, Pangolin documents delegation of the zone through NS, which transfers responsibility for the zone records. Keep the production zone outside this setup. This architecture has no required DNS vendor or inbound router ports. [Pricing](https://pangolin.net/pricing) · [Terms](https://pangolin.net/tos) · [Domains](https://docs.pangolin.net/manage/domains) · [Newt](https://docs.pangolin.net/manage/sites/install-newt)

Use a public HTTP/HTTPS resource to `http://127.0.0.1:18280` with managed TLS and direct MAI Food authentication so Telegram clients can reach the Mini App and the secret-checked webhook. For Kitchen, use a separate private HTTP/HTTPS resource to `http://127.0.0.1:18281`, allow named staff members through the Pangolin client and configure trusted private TLS for browser WSS. Confirm that the account's private resource supports the planned HTTPS name, TLS trust, and Upgrade forwarding in a live acceptance run. [Pangolin resources](https://docs.pangolin.net/manage/resources/understanding-resources)

**Tailscale Funnel and Serve.** Funnel can give the customer a stable `ts.net` name with managed HTTPS, subject to personal-plan eligibility, supported macOS clients, bandwidth limits, and approved tailnet policy. Funnel and private Serve need distinct HTTPS ports on one node. If used, assign Funnel port 443 to the customer listener and private Serve port 8443 to Kitchen. Check staff-only policy from both an authorized device and a device outside the tailnet. Use only if the existing VPN and host extension setup allow it. [Funnel limits](https://tailscale.com/docs/features/tailscale-funnel) · [Serve](https://tailscale.com/docs/features/tailscale-serve)

**ngrok Free.** Its assigned HTTPS development domain is suitable for a webhook-only connectivity trial insofar as the test traffic fits the 20,000 requests and 1 GB monthly transfer limits. The browser interstitial is a constraint for Telegram Mini App acceptance. Keep Kitchen local or use a separately approved private transport. [ngrok free limits](https://ngrok.com/docs/pricing-limits) · [Development domain and browser warning](https://ngrok.com/blog/free-static-domains-ngrok-users)

### Future acceptance on Wi-Fi and hotspot

1. Confirm eligibility, prepare a user-controlled staging HTTPS hostname, and have the owner supply a dedicated test bot through the staging env file. Keep only the customer listener behind the public connector and confirm a staff-only Kitchen resource.
2. On Wi-Fi, verify certificate hostname and trust, same-origin sign-in and cookie restore in Telegram, exact webhook with the test bot, and Kitchen WSS with a staff JWT. Independently confirm that the customer hostname returns 404 for the staff login and WebSocket routes and that the private Kitchen hostname is inaccessible to an unauthorized device. [Telegram webhook requirements](https://core.telegram.org/bots/api#setwebhook)
3. Move the Mac to the mobile hotspot with the connector still running. Capture outage and recovery timestamps. Repeat customer and staff HTTPS, WSS, and test webhook delivery checks on the same hostnames. Repeat when switching back. Verify recovery against the existing synthetic staging records. Preserve the current VPN and router configuration.
4. Stop or disable the staging routes and remove the test bot webhook after the session. Capture only status codes, elapsed time and redacted evidence.

Live tunnel routing, certificate issuance, hotspot reconnect and Telegram HTTPS delivery are external acceptance checks. Local staging needs none of these dependencies.
