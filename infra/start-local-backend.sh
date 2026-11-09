#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

settings=${1:-.env}
if [[ ! -f "$settings" ]]; then
    printf '%s\n' "Demo environment not found. Run python3 infra/local-demo.py up first, or pass the existing demo .env path." >&2
    exit 1
fi
# Match the existing demo project and volumes. Keep port 8080 for the customer-only gateway.
for setting in MINI_APP_PORT=8180 KITCHEN_APP_PORT=8181 POSTGRES_PORT=5544 KAFKA_PORT=9192; do
    if ! grep -Fxq "$setting" "$settings"; then
        printf 'Expected %s in the demo environment.\n' "$setting" >&2
        exit 1
    fi
done
compose=(docker compose --env-file "$settings" -p mai-food-demo -f docker-compose.yml -f compose.local-demo.yml -f compose.cloudflare-tunnel.yml)
"${compose[@]}" config --quiet
"${compose[@]}" up -d --build --wait --wait-timeout 300
for service in user-service menu-service order-service notification-service; do
    "${compose[@]}" run --rm --no-deps --entrypoint /app/.venv/bin/alembic "$service" upgrade head
done
"${compose[@]}" up -d --no-deps --force-recreate --wait proxy
curl -fsS http://127.0.0.1:8080/api/v1/menu/items >/dev/null
"${compose[@]}" --profile inbox --profile outbox up -d notification-inbox outbox-worker
"${compose[@]}" ps
