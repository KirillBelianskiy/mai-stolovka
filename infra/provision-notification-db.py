"""Explicit local upgrade for an existing PostgreSQL volume; never resets data or passwords."""

import subprocess
from pathlib import Path

SQL = r"""
\getenv notification_password NOTIFICATIONS_DB_PASSWORD
SELECT format('CREATE ROLE notifications_owner LOGIN NOSUPERUSER ' ||
  'NOCREATEDB NOCREATEROLE PASSWORD %L', :'notification_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='notifications_owner')
\gexec
SELECT 1 / CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname='notifications_owner'
  AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
  AND NOT rolreplication AND NOT rolbypassrls) THEN 1 ELSE 0 END;
SELECT 'CREATE DATABASE notifications_db OWNER notifications_owner'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname='notifications_db')
\gexec
SELECT 1 / CASE WHEN EXISTS (SELECT 1 FROM pg_database WHERE datname='notifications_db'
  AND pg_get_userbyid(datdba)='notifications_owner') THEN 1 ELSE 0 END;
REVOKE ALL ON DATABASE notifications_db FROM PUBLIC;
\connect notifications_db
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
"""


def main() -> None:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "run",
            "--rm",
            "-T",
            "--no-deps",
            "--entrypoint",
            "bash",
            "postgres",
            "-euc",
            'export PGPASSWORD="$POSTGRES_PASSWORD"; exec psql -h postgres '
            "-U bootstrap_admin -d postgres -v ON_ERROR_STOP=1",
        ],
        cwd=Path(__file__).resolve().parents[1],
        input=SQL,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if result.returncode:
        raise SystemExit("Notification DB provisioning failed; inspect configuration privately")
    print("Notification owner/database checked; no password reset, migration or worker launch")


if __name__ == "__main__":
    main()
