# MAI Food on one Yandex Compute Cloud VM

## Release and architecture

Deploy a reviewed commit that includes this overlay. The deployment was developed on top of the
combined Mac MVP candidate `64096b9`, which contains product PRs #58 and #60–#65.
Verify the release commit against the approved PR chain before cloning it on the server.

Caddy terminates HTTPS for `maistolovka.me` and `kitchen.maistolovka.me`. Only Caddy
publishes Docker host ports. The customer origin serves a static Mini App and an allowlisted
same-origin API. The separate Kitchen origin is restricted to operator-supplied source networks
and still requires staff authentication for staff operations. Caddy uses the existing JWT
verifier for the customer role check. Nginx keeps API prefix stripping, static frontend proxying,
and Kitchen WebSocket upgrades. The two Next.js exports ship in independent Nginx images.

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
5. Add DNS A records for the apex and Kitchen host at the authoritative DNS provider, using the
   assigned VM address. Check CAA and remove any stale AAAA records unless IPv6 is configured.
   Keep the existing production DNS until the release is approved. For pre-cutover tests
   use distinct approved hostnames with matching certificates and origins, or a local isolated
   rehearsal with an internal CA. Caddy obtains and renews public certificates when the real
   DNS and ports are reachable. DNS or CDN proxying in front of Caddy is outside this direct
   ingress configuration because the staff allowlist uses the actual connection address.

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
install -m 600 infra/production/env.example "$HOME/.config/mai-food/production.env"
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

```bash
env_file="$HOME/.config/mai-food/production.env"
python3 infra/production/deploy.py --env-file "$env_file" check
python3 infra/production/deploy.py --env-file "$env_file" build
python3 infra/production/deploy.py --env-file "$env_file" deploy
python3 infra/production/deploy.py --env-file "$env_file" status
```

Build runs serially to reduce memory pressure. If needed, use the same branch, launcher build,
and project name on a larger Linux runner with the same CPU architecture as the VM. Use
non-production fixture keys for configuration validation there. Transfer only the built Docker
images with `docker image save` / `docker image load` before deploying on the VM. Keep images available for the rollback window. Pass `--telegram` to both build and deploy when
explicitly activating real dispatch. A normal redeploy stops an existing dispatcher.
The launcher keeps the external volumes, stops application traffic and workers during
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
compose logs --tail=100 edge proxy websocket-service outbox-worker notification-inbox
compose exec -T postgres pg_isready -U bootstrap_admin -d postgres
compose exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:29092 --describe --topic orders.events.v1
curl -fsS https://maistolovka.me/api/v1/menu/categories
```

Verify HTTP redirects to HTTPS, certificate trust, client sign-in in Telegram, and a staff login
and WSS upgrade from an approved network. Validate a complete order, preparation, READY
notification and issuance with a controlled account. An unauthenticated Kitchen socket upgrade
alone does not verify authorization or realtime delivery. Check Kafka consumer groups and
worker logs, including lag and failed dispatch. Disabled workers have no readiness endpoint.
Provision staff and real catalog data through the approved local operator scripts and ADMIN
interfaces. Keep fixture seeding out of production. See [local operations](mac-staging.md)
and [readiness procedures](operations/readiness-runbook.md).

For updates, build the reviewed commit first, record the prior commit and image IDs, arrange a
maintenance window, take a verified backup, then deploy and rerun the smoke checks. Roll back
images only when the migrated schema remains compatible. For incompatible migrations, stop
writes and follow the rehearsed restore or forward-fix plan. Preserve any orders created after
the backup before making a state recovery decision. No auto-deploy workflow is enabled.
An optional next CI step is Compose config and Caddy validation with generated fixture keys,
followed by an isolated no-deploy smoke run on Linux.

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
uses 128 MiB shared buffers plus per-connection memory and cache. Static frontends use Nginx
at runtime, with Node only in the image build. The broker is capped at 1 GiB of retained data
per partition, plus active segment and auxiliary overhead. Retention can expire unread data.
Watch disk and lag. Use one VM and single replication for this pilot. Any VM, disk, or
broker loss can cause downtime.

Use 30 GiB as the initial disk planning figure for OS, layers, logs and data. Measure free
space before builds and upgrades. Treat 20 GiB as an option only with prebuilt images and
documented headroom. Build off-VM or temporarily increase RAM if builds exceed the VM budget.
Compare region-specific VM hours, disk, public IP, backups and outbound traffic in Yandex's
calculator before provisioning.
