"""Run User/Menu/Order integration tests in temporary service-owned PostgreSQL databases."""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def compose(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
        timeout=120,
    )


def admin_sql(query: str) -> None:
    compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "bootstrap_admin",
        "-d",
        "postgres",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        query,
    )


def main() -> None:
    values = dict(
        line.split("=", 1)
        for line in (ROOT / ".env").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    address = compose("port", "postgres", "5432").stdout.strip()
    for service, owner, password_key in (
        ("user", "users_owner", "USERS_DB_PASSWORD"),
        ("menu", "menu_owner", "MENU_DB_PASSWORD"),
        ("order", "orders_owner", "ORDERS_DB_PASSWORD"),
    ):
        name = f"mai_test_{service}_{uuid4().hex}"
        admin_sql(f"CREATE DATABASE {name} OWNER {owner}")
        try:
            admin_sql(f"REVOKE ALL ON DATABASE {name} FROM PUBLIC")
            environment = os.environ.copy()
            url = f"postgresql+asyncpg://{owner}:{values[password_key]}@{address}/{name}"
            environment.update(APP_DATABASE_URL=url, MAI_TEST_DATABASE_URL=url)
            directory = ROOT / "services" / f"{service}-service"
            binaries = directory / ".venv" / ("Scripts" if os.name == "nt" else "bin")
            subprocess.run(
                [str(binaries / "alembic"), "upgrade", "head"],
                cwd=directory,
                env=environment,
                check=True,
                timeout=60,
            )
            subprocess.run(
                [str(binaries / "python"), "-m", "pytest", "-m", "integration", "-q"],
                cwd=directory,
                env=environment,
                check=True,
                timeout=180,
            )
            subprocess.run(
                [str(binaries / "alembic"), "check"],
                cwd=directory,
                env=environment,
                check=True,
                timeout=60,
            )
            print(
                f"{service}-service: PostgreSQL integration and schema-drift checks passed",
                flush=True,
            )
        finally:
            admin_sql(f"DROP DATABASE {name} WITH (FORCE)")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        if error.stderr:
            print(error.stderr, file=sys.stderr)
        raise SystemExit(error.returncode) from None
