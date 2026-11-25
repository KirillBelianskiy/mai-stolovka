#!/usr/bin/env python3
"""Prepare and start the single-VM deployment without printing substituted values."""

import argparse
import base64
import binascii
import fcntl
import ipaddress
import os
import re
import stat
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "mai-food-prod"
DATABASES = ("user-service", "menu-service", "order-service", "notification-service")
PASSWORDS = (
    "POSTGRES_PASSWORD",
    "USERS_DB_PASSWORD",
    "MENU_DB_PASSWORD",
    "ORDERS_DB_PASSWORD",
    "NOTIFICATIONS_DB_PASSWORD",
)
VOLUMES = {
    "PROD_PG_VOLUME": "mai-food-prod-postgres",
    "PROD_KAFKA_VOLUME": "mai-food-prod-kafka",
    "PROD_TLS_VOLUME": "mai-food-prod-tls",
    "PROD_TLS_CONFIG_VOLUME": "mai-food-prod-tls-config",
}


def require(fields, name, pattern):
    if not re.fullmatch(pattern, fields.get(name, "")):
        raise SystemExit(f"Missing or invalid {name} in the production env file")


def configuration(path, telegram):
    if not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise SystemExit("Use a production env file with permissions 0600")
    if path.is_relative_to(ROOT):
        raise SystemExit("Store the production env file outside the repository")
    fields = {}
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = re.fullmatch(r"([A-Z][A-Z_0-9]*)=([^$'\"#]*)", line)
        if not match or match[1] in fields or match[2] != match[2].strip():
            raise SystemExit(f"Invalid or duplicate env assignment on line {number}")
        fields[match[1]] = match[2]
    for name in PASSWORDS:
        require(fields, name, r"[A-Fa-f0-9]{48,}")
    if len({fields[name] for name in PASSWORDS}) != len(PASSWORDS):
        raise SystemExit("Generate a different password for each database role")
    for name in ("PROD_WEBHOOK_ENABLED", "ORDER_DEMO_PAYMENTS_ENABLED"):
        if fields.get(name, "false") not in {"true", "false"}:
            raise SystemExit(f"{name} must be true or false")
    ranges = fields.get("PROD_KITCHEN_CIDRS", "").split()
    try:
        if not ranges or any(ipaddress.ip_network(value).prefixlen == 0 for value in ranges):
            raise ValueError
    except ValueError:
        raise SystemExit("Specify restricted Kitchen CIDRs in PROD_KITCHEN_CIDRS") from None
    pairs = [("JWT_PRIVATE_KEY_BASE64", "JWT_PUBLIC_KEY_BASE64")]
    if telegram:
        pairs.append(("NOTIFICATION_SIGNING_KEY_BASE64", "NOTIFICATION_SERVICE_PUBLIC_KEY_BASE64"))
    for private, public in pairs:
        try:
            private_pem = base64.b64decode(fields.get(private, ""), validate=True)
            public_pem = base64.b64decode(fields.get(public, ""), validate=True)
            key = subprocess.run(
                ["openssl", "rsa", "-pubout"],
                input=private_pem,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
            ).stdout
        except (binascii.Error, subprocess.CalledProcessError):
            raise SystemExit(f"Invalid RSA credentials in {private} / {public}") from None
        if key.strip() != public_pem.strip():
            raise SystemExit(f"RSA key pair does not match for {private} / {public}")
    if telegram or fields.get("TELEGRAM_BOT_TOKEN"):
        require(fields, "TELEGRAM_BOT_TOKEN", r"[0-9]+:[A-Za-z0-9_-]{20,}")
    if fields.get("PROD_WEBHOOK_ENABLED") == "true" or telegram:
        require(fields, "TELEGRAM_WEBHOOK_SECRET", r"[A-Za-z0-9_-]{32,256}")
    if telegram and fields.get("PROD_WEBHOOK_ENABLED") != "true":
        raise SystemExit("Enable the approved Telegram webhook before enabling the dispatcher")
    return fields


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--telegram", action="store_true", help="enable approved live delivery")
    parser.add_argument("action", choices=("check", "build", "deploy", "status"))
    args = parser.parse_args()
    path = args.env_file.resolve()
    fields = configuration(path, args.telegram)
    if VOLUMES.keys() & fields.keys():
        raise SystemExit("Production volume names are fixed by this launcher")
    env = {name: value for name, value in os.environ.items() if not name.startswith("COMPOSE_")}
    for name in {
        *fields,
        *VOLUMES,
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_WEBHOOK_SECRET",
        "NOTIFICATION_SERVICE_PUBLIC_KEY_BASE64",
        "NOTIFICATION_SIGNING_KEY_BASE64",
        "PROD_WEBHOOK_ENABLED",
        "ORDER_DEMO_PAYMENTS_ENABLED",
    }:
        env.pop(name, None)
    prefix = [
        "docker",
        "compose",
        "--project-name",
        PROJECT,
        "--env-file",
        str(path),
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.prod.yml",
        "--profile",
        "outbox",
        "--profile",
        "inbox",
    ]

    def run(*command):
        subprocess.run(command, cwd=ROOT, env=env, check=True)

    def compose(*command):
        run(*prefix, *command)

    if args.action == "status":
        compose("--profile", "telegram", "ps", "-a")
        return
    compose("--profile", "telegram", "config", "--quiet")
    if args.action == "check":
        return
    with (path.parent / ".mai-food-deploy.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another MAI Food build or deployment is running") from None
        if args.action == "build":
            if args.telegram:
                prefix.extend(("--profile", "telegram"))
            compose("--parallel", "1", "build")
            return
        for volume in VOLUMES.values():
            run("docker", "volume", "create", volume)
        # Validate before interrupting the live edge. The one-off container publishes no ports.
        compose(
            "run",
            "--rm",
            "--no-deps",
            "edge",
            "caddy",
            "validate",
            "--config",
            "/etc/caddy/Caddyfile",
            "--adapter",
            "caddyfile",
        )
        compose("--profile", "telegram", "stop", "notification-dispatch")
        compose(
            "stop",
            "edge",
            "outbox-worker",
            "notification-inbox",
            "websocket-service",
            *DATABASES,
        )
        # Older releases have an additional proxy container in the same Compose project.
        compose("--profile", "local-development-only", "stop", "proxy")
        compose("up", "-d", "--wait", "--wait-timeout", "180", "postgres", "kafka")
        for service in DATABASES:
            compose(
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "/app/.venv/bin/alembic",
                service,
                "upgrade",
                "head",
            )
        compose(
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
        )
        compose(
            "up",
            "-d",
            "--no-build",
            "--wait",
            "--wait-timeout",
            "180",
            "edge",
            "notification-service",
            "outbox-worker",
            "notification-inbox",
        )
        if args.telegram:
            compose(
                "--profile",
                "telegram",
                "up",
                "-d",
                "--no-build",
                "--wait",
                "--wait-timeout",
                "60",
                "notification-dispatch",
            )
        compose("--profile", "telegram", "ps", "-a")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"Deployment command failed with exit code {error.returncode}") from None
