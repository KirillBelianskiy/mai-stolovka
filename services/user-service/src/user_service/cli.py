"""Provision staff locally; no public signup or default account exists."""

import argparse
import asyncio
import sys
from getpass import getpass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from user_service.application.passwords import hash_password, normalize_login
from user_service.config import Settings
from user_service.domain.users import Role
from user_service.infrastructure.database import Database
from user_service.infrastructure.models import StaffCredential, User


async def provision_staff(
    login: str, full_name: str, role: Role, password: str, settings: Settings
) -> str:
    login = normalize_login(login)
    full_name = full_name.strip()
    if role == Role.CLIENT or not full_name or len(full_name) > 256:
        raise ValueError("A staff role and a full name of 1–256 characters are required")
    hashed = await asyncio.to_thread(hash_password, password)
    if not settings.database_url:
        raise ValueError("APP_DATABASE_URL is required")
    database = Database(
        settings.database_url.get_secret_value(), settings.readiness_timeout_seconds
    )
    try:
        async with database.sessions() as db, db.begin():
            user = User(full_name=full_name, role=role)
            db.add(user)
            await db.flush()
            db.add(StaffCredential(user_id=user.id, login=login, password_hash=hashed))
            user_id = str(user.id)
        return user_id
    finally:
        await database.close()


async def reset_password(login: str, password: str, settings: Settings) -> None:
    login = normalize_login(login)
    hashed = await asyncio.to_thread(hash_password, password)
    if not settings.database_url:
        raise ValueError("APP_DATABASE_URL is required")
    database = Database(
        settings.database_url.get_secret_value(), settings.readiness_timeout_seconds
    )
    try:
        async with database.sessions() as db, db.begin():
            credential = await db.scalar(
                select(StaffCredential).where(StaffCredential.login == login)
            )
            if credential is None:
                raise ValueError("Staff account does not exist")
            credential.password_hash = hashed
    finally:
        await database.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("provision-staff")
    create.add_argument("--username", required=True)
    create.add_argument("--full-name", required=True)
    create.add_argument("--role", choices=["COOK", "CASHIER", "ADMIN"], required=True)
    reset = sub.add_parser("reset-password")
    reset.add_argument("--username", required=True)
    args = parser.parse_args()
    if not sys.stdin.isatty():
        parser.exit(2, "An interactive terminal is required for secure password entry\n")
    password = getpass("Password (12–128 characters): ")
    if password != getpass("Confirm password: "):
        parser.exit(2, "Passwords do not match\n")
    try:
        settings = Settings()
        if args.command == "provision-staff":
            user_id = asyncio.run(
                provision_staff(args.username, args.full_name, Role(args.role), password, settings)
            )
            print(f"Created staff account {user_id}")
        else:
            asyncio.run(reset_password(args.username, password, settings))
            print(
                "Password updated; existing access tokens expire within their configured lifetime"
            )
    except IntegrityError:
        parser.exit(2, "Staff login already exists; no account was created\n")
    except ValueError as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
