# Cloudflare Pages and the local MAI Stolovka API

This setup runs the existing Compose services on an Apple Silicon Mac. Pages serves the
static Next.js export at `https://maistolovka.me`. A named Cloudflare Tunnel sends
`https://api.maistolovka.me` to the customer API listener at `http://127.0.0.1:8080`.
The listener reuses the existing Nginx router. The Pages apex record stays in place.

## Local setup

Install Docker Desktop, Python 3.12, OpenSSL and Homebrew. Start Docker Desktop and run
`brew install cloudflared`. If there is no existing demo, run `python3 infra/local-demo.py up`
once from this checkout to create credentials, migrations, the development topic and fixtures.
With an existing demo, use its original private environment and volumes.

Place the real BotFather token in the demo environment as `CLOUDFLARE_TELEGRAM_BOT_TOKEN`.
Keep the original synthetic setting for the local-only Compose configuration. In tunnel mode,
new synthetic launch URLs do not authenticate against the real bot token.

```sh
./infra/start-local-backend.sh /absolute/path/to/demo/.env
curl -fsS http://127.0.0.1:8080/api/v1/menu/items
```

The launcher reuses Compose project `mai-food-demo`, runs migrations and checks the API.
The full local interfaces remain on ports 8180 and 8181. Kafka and PostgreSQL bind to loopback.
Port 8080 is the customer gateway. Staff authentication, menu mutations, wallet credits, staff
order mutations, internal recipient routes and the kitchen WebSocket are outside its route
allowlist. Shared user and order endpoints also reject staff JWTs at the public gateway.
The kitchen WebSocket remains on 8181 with its existing Origin and staff authentication.

## Connect Cloudflare Tunnel

In the Cloudflare account that owns the domain, open **Networking → Tunnels**. Reuse a
tunnel dedicated to this Mac and API if present. Otherwise create a remotely managed named
tunnel, for example `mai-stolovka-backend`. Add the public hostname `api.maistolovka.me`
with service type **HTTP** and URL `127.0.0.1:8080`. The published hostname creates a
proxied CNAME to the tunnel. Inspect any existing `api` record before replacing it. The
root `maistolovka.me` record and Pages custom-domain binding stay as configured.

Save only the connector token shown by Cloudflare into a local file with mode 600.
For a foreground test, use its absolute path:

```sh
cloudflared tunnel --no-autoupdate run --token-file /absolute/path/to/private/tunnel-token
```

For supervised startup after Mac login, create a user LaunchAgent using the following command.
Set the absolute token file path first. The agent restarts the connector after process exits.
The token stays in the file instead of appearing in the process command line.

```sh
export MAI_TUNNEL_TOKEN_FILE=/absolute/path/to/private/tunnel-token
python3 - <<'PY'
import os
import plistlib
import shutil
from pathlib import Path

token = Path(os.environ["MAI_TUNNEL_TOKEN_FILE"]).resolve(strict=True)
binary = shutil.which("cloudflared")
if not binary or token.stat().st_mode & 0o077:
    raise SystemExit("Install cloudflared and restrict the token file to mode 600.")
agents = Path.home() / "Library/LaunchAgents"
agents.mkdir(parents=True, exist_ok=True)
with (agents / "me.maistolovka.cloudflared.plist").open("xb") as stream:
    plistlib.dump({
        "Label": "me.maistolovka.cloudflared",
        "ProgramArguments": [binary, "tunnel", "--no-autoupdate", "run", "--token-file", str(token)],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "StandardOutPath": str(Path.home() / "Library/Logs/maistolovka-cloudflared.log"),
        "StandardErrorPath": str(Path.home() / "Library/Logs/maistolovka-cloudflared.err.log"),
    }, stream)
PY
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/me.maistolovka.cloudflared.plist"
```

Verify the HTTPS route before publishing Pages:

```sh
curl -fsS https://api.maistolovka.me/api/v1/menu/items
curl -i -X OPTIONS https://api.maistolovka.me/api/v1/users/auth/session \
  -H 'Origin: https://maistolovka.me' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type'
curl -s -o /dev/null -w '%{http_code}\n' https://api.maistolovka.me/api/v1/menu/admin/items
```

Expected results are menu JSON, 204 with exact allowed Origin and credentials, and 404 for the
admin route. The user service checks exact Origin for session mutations and validates Telegram
initData before issuing its host-only Secure, HttpOnly, SameSite=Strict session cookie.
Authorization for the order APIs continues to use scoped bearer credentials.

## Publish Pages

In the existing Pages project, use the Git branch containing this change. Set repository root
to the monorepo root, Node to 22, build command to
`npm exec --workspace @mai/telegram-mini-app -- next build --webpack`, and output directory
to `apps/telegram-mini-app/out`. Set public build variable `NEXT_PUBLIC_API_ORIGIN` to
`https://api.maistolovka.me`. Next.js inlines it during build. Keep the variable unset in
local builds to use relative API paths. The bot and tunnel tokens belong on the Mac.

Before production promotion, verify the artifact is built from the intended commit. After
publication open [the existing Mini App](https://t.me/mai_stolovka_bot/maistolovka) in Telegram.
Verify six photos, login, session restore, and a synthetic checkout. The Pages preview domain
does not have the production Origin or same-site cookie properties.

## Operate and recover

Run the same launcher and environment after updating or restarting Docker Desktop. On Mac login,
start Docker Desktop before running the launcher. The LaunchAgent reconnects independently.
Sleep, loss of network, or shutdown makes the API unavailable. Pages continues to serve the
static frontend. Keep the Mac awake when the demo is in use.

From the tunnel checkout, use the same project and overlay to inspect or stop containers:

```sh
compose=(docker compose --env-file /absolute/path/to/demo/.env -p mai-food-demo -f docker-compose.yml -f compose.local-demo.yml -f compose.cloudflare-tunnel.yml)
"${compose[@]}" ps -a
"${compose[@]}" logs --tail 100 proxy user-service menu-service order-service
launchctl print "gui/$(id -u)/me.maistolovka.cloudflared"
tail -n 100 "$HOME/Library/Logs/maistolovka-cloudflared.err.log"
```

To disable public API access, remove the published hostname from the tunnel and remove the
API-only DNS record if it remains. Stop the connector with
`launchctl bootout "gui/$(id -u)/me.maistolovka.cloudflared"` or Ctrl+C in foreground mode.
To stop Compose while retaining the database, use `"${compose[@]}" --profile inbox --profile outbox stop`.
Keep the Compose project name and volumes when updating.

References: [Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/get-started/),
[Cloudflare connector tokens](https://developers.cloudflare.com/tunnel/reference/tunnel-tokens/),
[Next.js environment variables](https://nextjs.org/docs/pages/guides/environment-variables).
