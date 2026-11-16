"""Operate the isolated, synthetic local demonstration; never target an existing stack."""

import argparse
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from local_demo_menu import seed_menu

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".private" / "local-demo"
ACCESS = STATE / "access.json"
COMPOSE = [
    "docker",
    "compose",
    "-p",
    "mai-food-demo",
    "-f",
    "docker-compose.yml",
    "-f",
    "compose.local-demo.yml",
]
BASE = "http://localhost:8180"


def run(args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        stream.write(value)


def env():
    return dict(
        line.split("=", 1)
        for line in (ROOT / ".env").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )


def init():
    if not (ROOT / ".env").exists():
        run([sys.executable, "infra/create-local-env.py"])
        settings = env()
        settings.update(
            POSTGRES_PORT="5544",
            KAFKA_PORT="9192",
            MINI_APP_PORT="8180",
            KITCHEN_APP_PORT="8181",
            ORDER_DEMO_PAYMENTS_ENABLED="true",
            TELEGRAM_BOT_TOKEN="local-demo:" + secrets.token_hex(32),
        )
        save(ROOT / ".env", "\n".join(f"{key}={value}" for key, value in settings.items()) + "\n")
    settings = env()
    expected = {
        "POSTGRES_PORT": "5544",
        "KAFKA_PORT": "9192",
        "MINI_APP_PORT": "8180",
        "KITCHEN_APP_PORT": "8181",
    }
    if any(settings.get(key) != value for key, value in expected.items()) or not settings.get(
        "TELEGRAM_BOT_TOKEN", ""
    ).startswith("local-demo:"):
        raise SystemExit("Refusing a non-demo .env; existing credentials were not changed.")
    keys = [settings.get("JWT_PRIVATE_KEY_BASE64"), settings.get("JWT_PUBLIC_KEY_BASE64")]
    if any(keys) and not all(keys):
        raise SystemExit(
            "The local JWT key pair is incomplete; restore the matching pair explicitly."
        )
    if not any(keys):
        run([sys.executable, "infra/create-auth-env.py"])
    if not ACCESS.exists():
        save(ACCESS, json.dumps({"password": secrets.token_urlsafe(18)}, indent=2))


def request(method, path, body=None, token=None, key=None):
    headers = {"Content-Type": "application/json", "Origin": BASE}
    if token:
        headers["Authorization"] = "Bearer " + token
    if key:
        headers["Idempotency-Key"] = key
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        data = response.read()
        return json.loads(data) if data else None


def launch_data():
    values = {
        "auth_date": str(int(time.time())),
        "query_id": "local-demo",
        "user": json.dumps(
            {
                "id": 883000001,
                "first_name": "Анна",
                "last_name": "Демонстрационная",
                "username": "local_demo_anna",
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    secret = hmac.new(b"WebAppData", env()["TELEGRAM_BOT_TOKEN"].encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(
        secret, "\n".join(f"{key}={values[key]}" for key in sorted(values)).encode(), hashlib.sha256
    ).hexdigest()
    return urllib.parse.urlencode(values)


def seed():
    state = json.loads(ACCESS.read_text())
    # Provision only inside the dedicated demo User container, through its own application.
    code = """import asyncio,json,sys
from sqlalchemy import select
from user_service.cli import provision_staff
from user_service.config import Settings
from user_service.domain.users import Role
from user_service.infrastructure.database import Database
from user_service.infrastructure.models import StaffCredential
async def main():
    password=json.load(sys.stdin)['password']
    settings=Settings()
    db=Database(settings.database_url.get_secret_value(),settings.readiness_timeout_seconds)
    try:
        accounts = [('demo-admin','ADMIN','Администратор демо'),
                    ('demo-cook','COOK','Повар демо'),
                    ('demo-cashier','CASHIER','Кассир демо')]
        for login,role,name in accounts:
            async with db.sessions() as session:
                query=select(StaffCredential.user_id).where(StaffCredential.login==login)
                exists=await session.scalar(query)
            if exists is None:
                await provision_staff(login,name,Role(role),password,settings)
    finally:
        await db.close()
asyncio.run(main())
"""
    run(
        COMPOSE + ["exec", "-T", "user-service", "/app/.venv/bin/python", "-c", code],
        input=json.dumps({"password": state["password"]}),
        text=True,
    )
    admin = request(
        "POST",
        "/api/v1/users/auth/staff",
        {"username": "demo-admin", "password": state["password"]},
    )["access_token"]
    client = request("POST", "/api/v1/users/auth/telegram", {"init_data": launch_data()})
    items = seed_menu(request, BASE, admin)
    slots = request("GET", "/api/v1/orders/slots", token=admin)
    if len(slots) < 3:
        start = (datetime.now(UTC) + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
        for index in range(4):
            current = start + timedelta(minutes=30 * index)
            slots.append(
                request(
                    "POST",
                    "/api/v1/orders/slots",
                    {
                        "start_time": current.isoformat(),
                        "end_time": (current + timedelta(minutes=20)).isoformat(),
                        "capacity": 30,
                    },
                    admin,
                )
            )
    wallet = request("GET", "/api/v1/orders/wallet", token=client["access_token"])
    if wallet["balance"] < 100000:
        request(
            "POST",
            "/api/v1/orders/wallet/credits",
            {"user_id": client["user"]["id"], "amount": 200000},
            admin,
            str(uuid.uuid4()),
        )
    history = request("GET", "/api/v1/orders/", token=client["access_token"])
    if history["total"] == 0:
        for index, status in enumerate(["PENDING", "PREPARING", "READY"]):
            item = items[index]
            order = request(
                "POST",
                "/api/v1/orders/",
                {
                    "slot_id": slots[index]["id"],
                    "items": [{"menu_item_id": item["id"], "quantity": 1}],
                    "expected_total_amount": item["price"],
                },
                client["access_token"],
                str(uuid.uuid4()),
            )
            if status != "PENDING":
                order = request(
                    "PATCH",
                    "/api/v1/orders/" + order["id"] + "/status",
                    {"status": "PREPARING", "expected_version": order["version"]},
                    admin,
                )
            if status == "READY":
                request(
                    "PATCH",
                    "/api/v1/orders/" + order["id"] + "/status",
                    {"status": "READY", "expected_version": order["version"]},
                    admin,
                )
    state["client_id"] = client["user"]["id"]
    save(ACCESS, json.dumps(state, indent=2))
    print("Demo menu, future slots, wallet and three order states are available.")


def login(open_browser=False):
    url = BASE + "/#" + urllib.parse.urlencode({"tgWebAppData": launch_data()})
    save(STATE / "client-url.txt", url + "\n")
    print("Fresh client launch saved to .private/local-demo/client-url.txt (valid 5 minutes).")
    if open_browser:
        # No launch material is printed to a terminal or shared log.
        if sys.platform == "darwin":
            run(["open", url])
        else:
            import webbrowser

            webbrowser.open(url)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["up", "seed", "login", "status", "down"])
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    init()
    if args.command == "up":
        run(COMPOSE + ["config", "--quiet"])
        run(COMPOSE + ["up", "-d", "--build", "--wait", "--wait-timeout", "300"])
        # Nginx resolves upstream names at startup. A rebuild can change container IPs.
        run(COMPOSE + ["up", "-d", "--no-deps", "--force-recreate", "--wait", "proxy"])
        for service in ["user-service", "menu-service", "order-service", "notification-service"]:
            run(
                COMPOSE
                + [
                    "run",
                    "--rm",
                    "--no-deps",
                    "--entrypoint",
                    "/app/.venv/bin/alembic",
                    service,
                    "upgrade",
                    "head",
                ]
            )
        run(
            COMPOSE
            + [
                "exec",
                "-T",
                "kafka",
                "/opt/kafka/bin/kafka-topics.sh",
                "--bootstrap-server",
                "kafka:29092",
                "--create",
                "--if-not-exists",
                "--topic",
                "orders.events.v1",
                "--partitions",
                "1",
                "--replication-factor",
                "1",
                "--config",
                "cleanup.policy=delete",
                "--config",
                "retention.ms=604800000",
                "--config",
                "min.insync.replicas=1",
            ]
        )
        run(COMPOSE + ["--profile", "inbox", "up", "-d", "notification-inbox"])
        seed()
        run(COMPOSE + ["--profile", "outbox", "up", "-d", "outbox-worker"])
        login(args.open)
    elif args.command == "seed":
        seed()
    elif args.command == "login":
        login(args.open)
    else:
        run(
            COMPOSE
            + (
                ["ps", "-a"]
                if args.command == "status"
                else ["--profile", "outbox", "--profile", "inbox", "down"]
            )
        )


if __name__ == "__main__":
    main()
