"""Manage the isolated MAI Food Mac staging project and its pinned static exports."""

import argparse
import fcntl
import os
import re
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".private/mac-staging"
ARTIFACTS = STATE / "artifacts"
ENV_FILE = STATE / "staging.env"
BASELINE = "585f6147dc2c6fca6301d6e6339afd10f4991944"
APPS = ("telegram-mini-app", "kitchen-app")
SERVICES = ("user-service", "menu-service", "order-service", "notification-service")
COMPOSE = [
    "docker",
    "--context",
    "desktop-linux",
    "compose",
    "--project-name",
    "mai-food-mac-staging",
    "--env-file",
    str(ENV_FILE),
    "-f",
    "docker-compose.yml",
    "-f",
    "compose.mac-staging.yml",
    "--profile",
    "outbox",
    "--profile",
    "inbox",
]


def run(*args, cwd=ROOT, **kwargs):
    return subprocess.run(args, cwd=cwd, check=True, **kwargs)


def compose(*args, **kwargs):
    # Compose gives the shell priority over --env-file. Keep project settings self-contained.
    inherited = ("PATH", "HOME", "TMPDIR", "TERM", "USER", "LOGNAME", "DOCKER_CONFIG")
    env = {key: os.environ[key] for key in inherited if key in os.environ}
    run(*COMPOSE, *args, env=env, **kwargs)


def init():
    if ENV_FILE.exists():
        raise SystemExit(f"Staging configuration already exists at {ENV_FILE}")
    with tempfile.TemporaryDirectory(dir=STATE) as directory:
        setup = Path(directory)
        (setup / "infra").mkdir()
        for name in ("create-local-env.py", "create-auth-env.py"):
            shutil.copyfile(ROOT / "infra" / name, setup / "infra" / name)
        shutil.copyfile(ROOT / ".env.example", setup / ".env.example")
        run("python3", "infra/create-local-env.py", cwd=setup)
        run("python3", "infra/create-auth-env.py", cwd=setup)
        config = setup / ".env"
        config.write_text(
            config.read_text().replace(
                "TELEGRAM_BOT_TOKEN=\n",
                f"TELEGRAM_BOT_TOKEN=local-staging:{secrets.token_hex(32)}\n",
            )
        )
        with config.open("a") as stream:
            stream.write(
                "\nSTAGING_CUSTOMER_ORIGIN=http://localhost:18280\n"
                "STAGING_KITCHEN_ORIGIN=http://localhost:18281\n"
                "STAGING_WEBHOOK_ENABLED=false\n"
            )
        config.rename(ENV_FILE)
    print(f"Initialized {ENV_FILE}")


def select(revision):
    release = ARTIFACTS / revision
    if not all((release / app / "index.html").is_file() for app in APPS):
        raise SystemExit(f"Missing completed static release {revision}")
    with tempfile.TemporaryDirectory(dir=ARTIFACTS) as directory:
        link = Path(directory) / "current"
        link.symlink_to(revision)
        link.replace(ARTIFACTS / "current")
    print(f"Selected static release {revision}")


def build(revision):
    release = ARTIFACTS / revision
    if not release.exists():
        with tempfile.TemporaryDirectory(dir=STATE) as directory:
            workspace = Path(directory) / "source"
            workspace.mkdir()
            archive = Path(directory) / "source.tar"
            with archive.open("wb") as stream:
                run("git", "archive", revision, stdout=stream)
            run("tar", "-xf", str(archive), cwd=workspace)
            build_env = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("NEXT_PUBLIC_")
            }
            build_env.update(NEXT_PUBLIC_API_BASE_URL="/api/v1", NEXT_TELEMETRY_DISABLED="1")
            run("npm", "ci", cwd=workspace, env=build_env)
            run("npm", "run", "build", cwd=workspace, env=build_env)
            exports = Path(directory) / "exports"
            exports.mkdir()
            for app in APPS:
                output = workspace / "apps" / app / "out"
                if not (output / "index.html").is_file() or not (output / "_next/static").is_dir():
                    raise SystemExit(f"Incomplete export for {app}")
                output.rename(exports / app)
            exports.rename(release)
    select(revision)


def validate_config():
    if not ENV_FILE.is_file():
        raise SystemExit("Initialize this worktree with mac-staging.py init")
    fields = dict(
        line.split("=", 1)
        for line in ENV_FILE.read_text().splitlines()
        if "=" in line and not line.lstrip().startswith("#")
    )
    enabled = fields.get("STAGING_WEBHOOK_ENABLED")
    if enabled not in {"true", "false"}:
        raise SystemExit("Set STAGING_WEBHOOK_ENABLED to true or false")
    if enabled == "true" and not re.fullmatch(
        r"[A-Za-z0-9_-]{1,256}", fields.get("TELEGRAM_WEBHOOK_SECRET", "")
    ):
        raise SystemExit("An enabled webhook requires a valid Telegram webhook secret")
    for key, port in (("STAGING_CUSTOMER_ORIGIN", 18280), ("STAGING_KITCHEN_ORIGIN", 18281)):
        origin = fields.get(key, "")
        if origin != f"http://localhost:{port}" and not re.fullmatch(
            r"https://[a-z0-9-]+(\.[a-z0-9-]+)+(:(8443|10000))?", origin
        ):
            raise SystemExit(f"Set {key} to its localhost origin or one exact staging HTTPS origin")
    customer = fields["STAGING_CUSTOMER_ORIGIN"]
    kitchen = fields["STAGING_KITCHEN_ORIGIN"]
    if customer == kitchen or any(
        ".maistolovka.me" in f".{origin.split('://')[1].split(':')[0]}."
        for origin in (customer, kitchen)
    ):
        raise SystemExit("Use separate staging origins outside the production domain")
    compose("config", "--quiet")


def up():
    validate_config()
    if not all((ARTIFACTS / "current" / app / "index.html").is_file() for app in APPS):
        raise SystemExit("Build the pinned exports with mac-staging.py build")
    compose("up", "-d", "--wait", "--wait-timeout", "300", "postgres", "kafka")
    compose(
        "build",
        *SERVICES,
        "websocket-service",
        "customer-role",
        "notification-inbox",
        "outbox-worker",
    )
    for service in SERVICES:
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
        "--config",
        "min.insync.replicas=1",
    )
    compose("up", "-d", "notification-inbox", "outbox-worker")
    compose(
        "up",
        "-d",
        "--wait",
        "--wait-timeout",
        "300",
        "notification-service",
        "staging-ingress",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "build", "select", "up", "status", "down"))
    parser.add_argument("revision", nargs="?")
    args = parser.parse_args()
    if args.revision and args.action not in {"build", "select"}:
        parser.error("a revision is accepted only for build or select")
    revision = args.revision or BASELINE
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        parser.error("provide a full commit SHA")
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    ARTIFACTS.mkdir(exist_ok=True)
    with (STATE / "lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.action == "init":
            init()
        elif args.action == "build":
            build(revision)
        elif args.action == "select":
            select(revision)
        elif args.action == "up":
            up()
        elif args.action == "status":
            compose("ps", "-a")
        else:
            compose("down")


if __name__ == "__main__":
    main()
