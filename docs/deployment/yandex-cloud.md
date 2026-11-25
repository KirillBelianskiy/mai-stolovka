# MAI Food on one Yandex Compute Cloud VM

## Release and architecture

Deploy a reviewed commit that includes this overlay. The deployment was developed on top of the
combined Mac MVP candidate `64096b9`, which contains product PRs #58 and #60–#65.
Verify the release commit against the approved PR chain before cloning it on the server.

Caddy terminates HTTPS for `maistolovka.me` and `kitchen.maistolovka.me`. Only Caddy
publishes Docker host ports. The customer origin serves a static Mini App and an allowlisted
same-origin API. The separate Kitchen origin is restricted to operator-supplied source networks
and still requires staff authentication for staff operations. Caddy uses the existing JWT
verifier for the customer role check. The public Caddy service (`edge`) strips API prefixes,
routes directly to FastAPI, and upgrades Kitchen connections to WebSocket. Both Next.js exports
use internal Caddy static servers. Upstreams use Docker DNS on the existing default network.
Production leaves the local HTTP proxy disabled.

The production Caddyfile enables ACME, renewal, HTTP redirects, zstd/gzip, and access logs.
The existing TLS volumes back `/data` and `/config`. Access logs omit the Telegram webhook
secret header, Authorization, Cookie, Set-Cookie, Referer, and known token/initData query parameters. The public URL allowlists, Kitchen source
CIDRs, 128 kB body limit, forwarding header cleanup and client role check stay in effect.
Caddy adds its own client IP, host and scheme forwarding headers.

Staff login uses a pinned Caddy module built with the official Caddy builder. It allows
10 requests per source IP in a rolling minute, then returns 429. The previous limiter used
an initial burst followed by gradual refill.

| Component | Data and dependencies |
| --- | --- |
| User | `users_db` / `users_owner`, Telegram initData, sessions, JWTs, recipient preferences and webhook receipts |
| Menu | `menu_db` / `menu_owner`, categories and dishes |
| Order | `orders_db` / `orders_owner`, HTTP Menu lookup, slots, lifecycle, demo ledger and transactional Outbox |
| Notification | `notifications_db` / `notifications_owner`, durable inbox and READY delivery state |
| WebSocket | Staff JWT and Origin validation, independent Kafka consumer group, REST remains authoritative |
| Workers | Outbox publishes `orders.events.v1`; Notification inbox and Kitchen consume in separate groups. Optional dispatcher checks User over private HTTP and sends to Telegram. |

PostgreSQL and single-node Kafka KRaft keep separate persistent volumes. Kafka's internal
listener is `kafka:29092`, its controller listener is `29093`, and the order topic starts
with one partition and replication factor one. The launcher enables Outbox and inbox explicitly.
Live Telegram dispatch is opt-in. The demo wallet is opt-in and has no real payment provider.
Clean databases start without menu items, slots, or staff accounts.

## Create a VM

1. In Yandex Cloud, create a Linux **Ubuntu 24.04 LTS** VM. Start with **2 dedicated vCPU,
   4 GiB RAM and a 30 GiB SSD** as a pilot sizing hypothesis. Reserve a public IPv4 if the same
   DNS records must survive stop/start. Turn off automatic boot disk deletion if you need the
   disk retained on VM deletion. Review the estimated cost before creation.
2. Use a custom security group attached to the VM. Allow inbound TCP 80 and 443 from the
   internet and TCP 22 from your current public address, preferably an IPv4 `/32`.
   Use only the outbound access needed by package registries, DNS, TLS and Telegram. Permit
   replies to legitimate connections. Check for other attached security groups that could
   widen ingress. Do not open database, Kafka, Docker API, Caddy administration or service ports.
3. Supply your SSH **public** key when creating the VM. Connect as the user created in the
   console, verify the server fingerprint using a trusted channel, and confirm a second key-based
   session works before disabling SSH password authentication. Use an administrator you control.
4. Install Git, Python 3, OpenSSL and Docker Engine with the Compose plugin from Docker's
   official Ubuntu apt repository. For example, once that repository is configured, install
   `docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin`.
   Verify with `docker compose version` and enable the daemon with
   `sudo systemctl enable --now docker`. Use Compose **2.24.4 or later** for the overlay tags.
   Docker group membership gives root-equivalent access. If using sudo, run the same launcher
   consistently with sudo and give its operator access to the external env file.
5. Reserve a static public IPv4 in Yandex Cloud and assign it to the VM. Record the previous
   DNS records and TTLs before switching traffic.

| Ingress protocol | Port | Source |
| --- | --- | --- |
| TCP | 80 | `0.0.0.0/0` |
| TCP | 443 | `0.0.0.0/0` |
| TCP | 22 | Trusted administrator public IPv4 as a `/32` |

Check all attached groups for broader SSH rules and confirm a second SSH connection
before removing the previous rule.

### Namecheap DNS

Check delegation with `dig +short NS maistolovka.me`. With Namecheap BasicDNS,
PremiumDNS or FreeDNS active, open **Domain List → Manage → Advanced DNS → Host Records**.

| Record | Host | Value |
| --- | --- | --- |
| A | `@` | Static public IPv4 of the Yandex VM |
| A | `kitchen` | Same static public IPv4 |

Remove stale A, AAAA, CNAME/ALIAS or URL Redirect records that compete for either host.
Keep mail and ownership records. Check that any CAA policy permits Caddy's ACME issuers.
If nameservers are delegated elsewhere, prepare the full DNS zone before changing delegation.
Both hosts should resolve directly to the VM, since Kitchen authorizes the TCP peer address.
[Namecheap A records](https://www.namecheap.com/support/knowledgebase/article.aspx/319/2237/how-can-i-set-up-an-a-address-record-for-my-domain/)

```sh
for host in maistolovka.me kitchen.maistolovka.me; do
  dig +short "$host" A
  dig +short "$host" AAAA
  dig +short "$host" CAA
done
```

[Create a Yandex Linux VM](https://yandex.cloud/en/docs/compute/operations/vm-create/create-linux-vm) ·
[Yandex SSH and security groups](https://yandex.cloud/en/docs/getting-started/individuals/create-vm) ·
[Install Docker on Ubuntu](https://docs.docker.com/engine/install/ubuntu/) ·
[Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https)

## Prepare secrets and start

Put the reviewed checkout in a dedicated folder. Copy the environment template outside the
checkout with owner-only permissions, and fill in the values using an editor. The launcher
accepts plain `NAME=value` lines. Use no quotes or shell substitution in the file.

```bash
mkdir -p "$HOME/.config/mai-food"
if [ ! -e "$HOME/.config/mai-food/production.env" ]; then
  install -m 600 infra/production/env.example "$HOME/.config/mai-food/production.env"
fi
```

- Generate a separate `openssl rand -hex 32` value for each database password. Do not
  replace these values after first initialization without also rotating the database roles.
- Generate the User JWT RSA key pair on the host with a restrictive umask. Use
  `openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out private.pem`
  and `openssl pkey -in private.pem -pubout -out public.pem`. Encode each PEM as one line
  with `base64 -w0` on Ubuntu and paste into the corresponding env field without copying it
  to chat or logs. Keep the private PEM in protected storage or remove the temporary copy.
- Fill `TELEGRAM_BOT_TOKEN` from the approved bot. An empty token allows an infrastructure
  rehearsal, but real Mini App login requires the actual bot token at User.
- Set `PROD_KITCHEN_CIDRS` to space-separated source CIDRs for staff, such as a verified
  institutional egress range or approved fixed addresses. Keep the host off public DNS until
  the real allowlist is prepared. A different NAT egress or a mobile network may require an
  allowlist update. Confirm denied access from an outside network.
- Leave `PROD_WEBHOOK_ENABLED=false` until approval to accept Telegram updates. For approved
  live delivery, generate a separate RSA signing pair for Notification, fill in both Notification
  key fields and a fresh webhook secret, then set `PROD_WEBHOOK_ENABLED=true`. Register only
  the exact HTTPS PostgreSQL-deduplicated User webhook path
  `/api/v1/users/internal/v1/telegram/webhook` with the same secret via Telegram's
  `setWebhook`. Check for an existing webhook or polling consumer before changing update routing.
  Use a controlled test bot for first acceptance. Keep Telegram tokens out of shell arguments,
  command history, logs and URLs you share. [Telegram webhook](https://core.telegram.org/bots/api#setwebhook)

Before cutting over, inspect the current host listeners and running containers.

```sh
sudo ss -ltnp '( sport = :80 or sport = :443 )'
docker ps --format 'table {{.Names}}\t{{.Ports}}'
sudo systemctl is-active nginx
sudo systemctl is-enabled nginx
```

If host Nginx owns either port, identify its sites and save its configuration and service state.
If it serves MAI Food only, run `sudo systemctl stop nginx` in the cutover window after the
build and Caddy validation succeed. Disable it with `sudo systemctl disable nginx` after the new deployment passes the
checks below. If other sites share the listeners, coordinate their migration first. For the
existing Compose setup, the launcher stops the previous proxy and reuses the same TLS volumes.

```bash
env_file="$HOME/.config/mai-food/production.env"
python3 infra/production/deploy.py --env-file "$env_file" check
python3 infra/production/deploy.py --env-file "$env_file" build
python3 infra/production/deploy.py --env-file "$env_file" validate
# At this point, stop the old host ingress if applicable.
# Run in the approved cutover window.
python3 infra/production/deploy.py --env-file "$env_file" deploy
python3 infra/production/deploy.py --env-file "$env_file" status
```

Build runs serially to reduce memory pressure. If needed, use the same branch, launcher build,
and project name on a larger Linux runner with the same CPU architecture as the VM. Use
non-production fixture keys for configuration validation there. Transfer only the built Docker
images with `docker image save` / `docker image load` before deploying on the VM. Keep images available for the rollback window. Pass `--telegram` to both build and deploy when
explicitly activating real dispatch. A normal redeploy stops an existing dispatcher.
The `validate` command checks the built Caddy configuration without publishing ports. The launcher
validates again before it stops existing Compose services. It keeps the external volumes,
stops application traffic and workers during
migration, waits for PostgreSQL and Kafka, upgrades all four Alembic schemas, provisions the
order topic, then starts the services and workers. On an error, inspect the failed phase before
repeating deployment. The launcher never runs `down -v`.

## Operate, update and recover

For commands below, define the `compose` helper in a clean shell with no conflicting exported
production env keys. Do not run plain `docker compose config` or dump container environment.

```bash
compose() {
  docker compose -p mai-food-prod --env-file "$env_file" \
    -f docker-compose.yml -f docker-compose.prod.yml \
    --profile outbox --profile inbox --profile telegram "$@"
}
compose ps -a
compose logs --tail=100 edge websocket-service outbox-worker notification-inbox
compose exec -T edge caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
compose exec -T postgres pg_isready -U bootstrap_admin -d postgres
compose exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:29092 --describe --topic orders.events.v1
curl -sSI http://maistolovka.me/
curl -sSI http://kitchen.maistolovka.me/
curl -fsS -o /dev/null https://maistolovka.me/
curl -fsS https://maistolovka.me/api/v1/menu/categories
curl -sS -o /dev/null -w '%{http_code}\n' https://maistolovka.me/api/v1/users/auth/staff
curl -sS -o /dev/null -w '%{http_code}\n' https://kitchen.maistolovka.me/
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H 'Content-Type: application/json' -d '{"update_id":1}' \
  https://maistolovka.me/api/v1/users/internal/v1/telegram/webhook
```

Expect 308 on HTTP, trusted TLS on both hosts, and 404 for customer-origin staff login.
Kitchen returns 200 from an approved source network and 403 outside the list. The exact
webhook POST returns 404 when disabled and 403 without a secret when enabled.
From an approved network, sign in to Kitchen as staff. In browser DevTools under Network → WS,
verify a `101` for `wss://kitchen.maistolovka.me/api/v1/ws/kitchen` and check that a new order
arrives over that connection. Verify client sign-in in Telegram. Validate a complete order,
preparation, READY
notification and issuance with a controlled account. An unauthenticated Kitchen socket upgrade
alone does not verify authorization or realtime delivery. Check Kafka consumer groups and
worker logs, including lag and failed dispatch. Disabled workers have no readiness endpoint.
Provision an initial administrator from the VM and set its password at the interactive prompt.

```bash
compose exec user-service /app/.venv/bin/python -m user_service.cli provision-staff \
  --username "$staff_username" --full-name "$staff_full_name" --role ADMIN
```

Set the two shell variables to the approved staff member's login and name. Then use the
ADMIN interface to enter the real catalog and future pickup slots. Keep fixture seeding
out of production. See [local operations](mac-staging.md)
and [readiness procedures](operations/readiness-runbook.md).

For updates, build the reviewed commit first, record the prior commit and image IDs, arrange a
maintenance window, take a verified backup, then deploy and rerun the smoke checks. Roll back
images only when the migrated schema remains compatible. For incompatible migrations, stop
writes and follow the rehearsed restore or forward-fix plan. Preserve any orders created after
the backup before making a state recovery decision. No auto-deploy workflow is enabled.
CI validates both Compose models and the production Caddyfile with fixture settings. The local
Compose smoke suite checks API routing, the webhook boundary and the Kitchen WebSocket upgrade.

### Roll back the proxy migration

Record the exact previous release and keep it available. Back up PostgreSQL, Kafka and the
production environment before deployment. This proxy migration adds no schema migration on
top of `f0202c1`. Check schema compatibility when rolling back to another base.
Run the previous release from its own checkout with the same production environment,
Compose project and volume names.

```sh
# Set previous_release to the approved prior commit.
git worktree add --detach ../mai-food-previous "$previous_release"
(
  cd ../mai-food-previous || exit
  python3 infra/production/deploy.py --env-file "$env_file" check &&
  python3 infra/production/deploy.py --env-file "$env_file" build &&
  python3 infra/production/deploy.py --env-file "$env_file" deploy
)
```

If the old release used live dispatch, pass `--telegram` to its build and deploy commands.
For host Nginx, stop the new Compose `edge` to free ports 80/443, run `sudo nginx -t`,
start Nginx, and restore the previous enabled state. Restore saved DNS records if the previous
endpoint was elsewhere. Recheck HTTP, HTTPS, API and Kitchen from the approved network.
Keep the PostgreSQL, Kafka and TLS volumes.

For a coordinated recovery point, use a maintenance window. Stop ingress and writers,
including the outbox, inbox, and dispatcher before exporting state. Store encrypted backups
off the VM. The four databases have distinct owners. Keep the required role credentials
and bootstrap configuration separately in secure storage.

```bash
umask 077
mkdir -p "$backup_dir"
for db in users_db menu_db orders_db notifications_db; do
  compose exec -T postgres pg_dump -U bootstrap_admin -Fc "$db" > "$backup_dir/$db.dump" || exit 1
done
sha256sum "$backup_dir"/*.dump > "$backup_dir/SHA256SUMS"
```

Before resuming work, record Kafka consumer positions with
`compose exec -T kafka /opt/kafka/bin/kafka-consumer-groups.sh --bootstrap-server kafka:29092 --all-groups --describe`
and capture broker state at the
same quiesced point, for example with a protected disk snapshot after clean shutdown. Logical
PostgreSQL dumps alone cannot reconstruct the broker and its offsets. Restore first into an
isolated fresh project with its own volumes and roles. Verify checksums, then pipe each dump
to `pg_restore -U bootstrap_admin --clean --if-exists --exit-on-error -d DATABASE` in the
target PostgreSQL container. Verify owner/schema, orders, wallet, idempotency, Outbox and
Notification obligations. Keep consumers stopped until broker data and offsets reconcile.
A gap requires operator reconciliation. Never point an unverified restore at the live bot.

After a normal VM reboot, Docker starts and running services restart under
`unless-stopped`. Compose health dependencies are not a reboot orchestration service.
Verify broker assignment, migrations and worker progress before accepting traffic after
unplanned downtime. If the stack was manually stopped, rerun the approved launch steps.
After the defense, take an encrypted off-VM backup, stop the stack with `compose stop`, then
stop the VM in Yandex Cloud. Compute billing stops when the VM is stopped. Persistent disks,
snapshots and applicable reserved IP charges can continue. Release resources only after
retention and DNS changes are approved. Do not use `down -v`, volume pruning, or disk deletion
as routine shutdown. [Yandex Compute pricing](https://yandex.cloud/en/docs/compute/pricing) ·
[Yandex public IP pricing](https://yandex.cloud/en/docs/vpc/pricing)

## Resource budget

One idle Docker Desktop run of the 14-container stack measured about **1.24 GiB combined**
with Docker allocating 7.75 GiB to its Linux VM. Kafka used 568 MiB, PostgreSQL 143 MiB,
and the Python containers 39–80 MiB each. This excludes host OS, Docker overhead, build
peaks, live dispatch, and a sustained workload. It supports starting a measured 4 GiB pilot.
It does not qualify 4 GiB under load or prove cold builds fit. Check memory, OOM events,
swap activity, disk headroom, and order latency before accepting a pilot.
Kafka's Java heap is set to 256–512 MiB. The JVM also consumes non-heap memory. PostgreSQL
uses 128 MiB shared buffers plus per-connection memory and cache. Static frontends use Caddy
at runtime, with Node only in the image build. The broker is capped at 1 GiB of retained data
per partition, plus active segment and auxiliary overhead. Retention can expire unread data.
Watch disk and lag. Use one VM and single replication for this pilot. Any VM, disk, or
broker loss can cause downtime.

Use 30 GiB as the initial disk planning figure for OS, layers, logs and data. Measure free
space before builds and upgrades. Treat 20 GiB as an option only with prebuilt images and
documented headroom. Build off-VM or temporarily increase RAM if builds exceed the VM budget.
Compare region-specific VM hours, disk, public IP, backups and outbound traffic in Yandex's
calculator before provisioning.

## Repository release gate

The `production-release` GitHub Actions job runs `tests/e2e/production_release.py` on the
checked-out revision. It generates temporary keys, synthetic identities and disposable volumes.
Only random IPv4 loopback HTTP/TLS ports are published; PostgreSQL and Kafka stay internal.
The TLS issuer is changed to a local CA while every production route comes from the actual
production Caddyfile. Certificate and hostname verification remain enabled. No public DNS,
ACME, real Telegram account or production secret is used. The fake dispatcher cannot receive
a real bot token. Reports are sanitized and uploaded as workflow artifacts.

The gate compares baseline Nginx routes with Caddy against the same backends/exports, verifies
Mac static artifact switching and rollback, cookie restoration/logout, private APIs, roles,
wallet/booking replay and refund, webhook flag/secret/replay, staff login rolling limit,
network denial, authenticated WSS reconnect and Kafka hints, one fake READY delivery, and
an upgrade over the same disposable volumes. See [release evidence](../verification-caddy-release.md)
for exact revision and results. This gate does not qualify the public VM or real-device rollout.

## Historical rehearsal before the Nginx removal

The Docker builds, four migrations, Kafka topic provisioning and startup completed in
isolated local Compose. With a disposable Caddy CA and loopback test ports, both frontend
hosts and their API routes responded over TLS. HTTP redirected with 308. Customer routes
rejected a staff credential and blocked staff login, wallet credit, internal webhook and
Kitchen WebSocket access. Kitchen WSS accepted a COOK credential and rejected a CLIENT
credential and a foreign Origin. Live Telegram dispatch stayed disabled.

The existing API acceptance harness passed all 11 stages in a separate disposable stack,
including synthetic Telegram authentication, duplicate checkout, refund, repricing and cashier
issuance. Both exports and frontend typechecks passed with Node 22.22.2. Docker Desktop is
not the target 4 GiB Ubuntu VM. Before rollout, verify public certificates and DNS, the staff
network rule from real devices, live Telegram delivery, reboot recovery, a PostgreSQL and
Kafka restore exercise, and resource use under the intended load.
