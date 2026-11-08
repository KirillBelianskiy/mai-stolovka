"""Integration checks for an already running disposable Compose stack."""

import json
import secrets
import subprocess
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ("user", "menu", "order", "notification", "websocket")
DATABASES = (
    ("users", "user"),
    ("menu", "menu"),
    ("orders", "order"),
    ("notifications", "notification"),
)


def compose(
    *arguments: str, check: bool = True, input_text: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", *arguments],
        cwd=ROOT,
        check=check,
        capture_output=True,
        input=input_text,
        text=True,
        timeout=120,
    )


def origin(port: int) -> str:
    address = compose("port", "proxy", str(port)).stdout.strip()
    return f"http://{address}"


def sql(prefix: str, database: str, query: str) -> subprocess.CompletedProcess[str]:
    # Password expansion happens inside the container; credentials are not command arguments.
    return compose(
        "exec",
        "-T",
        "postgres",
        "bash",
        "-euc",
        f'export PGPASSWORD="${prefix.upper()}_DB_PASSWORD"; '
        'exec psql -h 127.0.0.1 -U "$1" -d "$2" -At -v ON_ERROR_STOP=1 -c "$3"',
        "--",
        f"{prefix}_owner",
        database,
        query,
        check=False,
    )


class StackSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mini = origin(8080)
        cls.kitchen = origin(8081)
        for service in ("user", "menu", "order", "notification"):
            compose(
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "/app/.venv/bin/alembic",
                f"{service}-service",
                "upgrade",
                "head",
            )

    def test_frontends_and_all_health_routes(self) -> None:
        for base, title in ((self.mini, "Обед в МАИ"), (self.kitchen, "Рабочее место столовой")):
            with self.subTest(origin=base):
                with urlopen(f"{base}/", timeout=10) as response:
                    self.assertIn(title, response.read().decode())
            for service in SERVICES:
                for endpoint, status in (("live", "alive"), ("ready", "ready")):
                    with self.subTest(origin=base, service=service, endpoint=endpoint):
                        with urlopen(f"{base}/health/{service}/{endpoint}", timeout=10) as response:
                            self.assertEqual(
                                json.load(response),
                                {
                                    "service": f"{service}-service",
                                    "status": status,
                                },
                            )

    def test_api_prefix_forwarding_and_reserved_websocket(self) -> None:
        for service, prefix in (("user", "users"), ("menu", "menu"), ("order", "orders")):
            with urlopen(f"{self.mini}/api/v1/{prefix}/health/live", timeout=10) as response:
                self.assertEqual(json.load(response)["service"], f"{service}-service")
        for path in ("/api/v1/ws/kitchen", "/api/v1/orders/not-implemented/unknown"):
            with self.subTest(path=path), self.assertRaises(HTTPError) as error:
                urlopen(f"{self.mini}{path}", timeout=10)
            self.assertEqual(error.exception.code, 404)

    def test_database_connections_and_isolation(self) -> None:
        for prefix, _ in DATABASES:
            result = sql(prefix, f"{prefix}_db", "SELECT current_user")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), f"{prefix}_owner")
            result = sql(
                prefix,
                f"{prefix}_db",
                "SELECT rolsuper, rolcreatedb, rolcreaterole "
                "FROM pg_roles WHERE rolname = current_user",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "f|f|f")
            result = sql(
                prefix,
                f"{prefix}_db",
                "SELECT pg_get_userbyid(datdba) "
                "FROM pg_database WHERE datname = current_database()",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), f"{prefix}_owner")
            for other, _ in DATABASES:
                if other == prefix:
                    continue
                with self.subTest(role=prefix, forbidden_database=other):
                    result = sql(prefix, f"{other}_db", "SELECT 1")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("permission denied for database", result.stderr)

    def test_alembic_expected_schema(self) -> None:
        expected = {
            "users": {"users", "staff_credentials", "user_sessions"},
            "menu": {"categories", "menu_items"},
            "notifications": {
                "source_checkpoints",
                "source_receipts",
                "notification_inbox",
                "order_observations",
                "observed_versions",
                "ready_obligations",
            },
            "orders": {
                "time_slots",
                "orders",
                "order_items",
                "idempotency_records",
                "outbox_events",
                "demo_wallets",
                "demo_credit_requests",
                "demo_ledger",
            },
        }
        for prefix, _ in DATABASES:
            with self.subTest(database=prefix):
                result = sql(
                    prefix,
                    f"{prefix}_db",
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name <> 'alembic_version'",
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(set(result.stdout.splitlines()), expected[prefix])

    def test_kafka_broker_ready(self) -> None:
        result = compose(
            "exec",
            "-T",
            "kafka",
            "/opt/kafka/bin/kafka-broker-api-versions.sh",
            "--bootstrap-server",
            "kafka:29092",
        )
        self.assertIn("29092", result.stdout)

    def test_staff_login_profile_and_admin_menu_flow(self) -> None:
        login = "smoke-" + uuid4().hex
        password = secrets.token_urlsafe(32)
        provision = """
import asyncio, json, sys
from user_service.cli import provision_staff
from user_service.config import Settings
from user_service.domain.users import Role
value = json.load(sys.stdin)
print(asyncio.run(provision_staff(
    value['login'], 'Smoke Test', Role.ADMIN, value['password'], Settings()
)))
"""
        result = compose(
            "exec",
            "-T",
            "user-service",
            "/app/.venv/bin/python",
            "-c",
            provision,
            input_text=json.dumps({"login": login, "password": password}),
        )
        user_id = result.stdout.strip()
        category_id = item_id = None
        headers = {}

        def request(
            method: str, path: str, body: object = None, authenticated: bool = False
        ) -> tuple[int, object]:
            data = None if body is None else json.dumps(body).encode()
            current_headers = {"Content-Type": "application/json"}
            if authenticated:
                current_headers.update(headers)
            value = Request(self.mini + path, data=data, headers=current_headers, method=method)
            try:
                response = urlopen(value, timeout=10)
            except HTTPError as error:
                response = error
            with response:
                content = response.read()
                return response.status, json.loads(content) if content else None

        try:
            status, value = request(
                "POST", "/api/v1/users/auth/staff", {"username": login, "password": password}
            )
            self.assertEqual(status, 200)
            self.assertEqual(value["user"]["role"], "ADMIN")
            self.assertEqual(value["user"]["id"], user_id)
            headers["Authorization"] = "Bearer " + value["access_token"]
            self.assertEqual(request("GET", "/api/v1/users/me", authenticated=True)[0], 200)
            self.assertEqual(
                request(
                    "POST", "/api/v1/users/auth/staff", {"username": login, "password": "incorrect"}
                )[0],
                401,
            )
            self.assertEqual(
                request("POST", "/api/v1/menu/categories", {"name": "No auth"})[0], 401
            )
            status, category = request("POST", "/api/v1/menu/categories", {"name": login}, True)
            self.assertEqual(status, 201)
            category_id = category["id"]
            status, item = request(
                "POST",
                "/api/v1/menu/items",
                {"category_id": category_id, "name": login, "price": 12000},
                True,
            )
            self.assertEqual(status, 201)
            item_id = item["id"]
            self.assertEqual(request("GET", f"/api/v1/menu/items/{item_id}")[0], 200)
            with urlopen(self.mini + "/api/v1/users/openapi.json", timeout=10) as response:
                self.assertIn("/auth/staff", json.load(response)["paths"])
            with urlopen(self.mini + "/api/v1/menu/docs", timeout=10) as response:
                self.assertIn("/api/v1/menu/openapi.json", response.read().decode())
        finally:
            if item_id:
                request("DELETE", f"/api/v1/menu/items/{item_id}", authenticated=True)
            if category_id:
                request("DELETE", f"/api/v1/menu/categories/{category_id}", authenticated=True)
            cleanup = """
import asyncio, sys
from uuid import UUID
from sqlalchemy import delete
from user_service.config import Settings
from user_service.infrastructure.database import Database
from user_service.infrastructure.models import User
async def remove():
    settings = Settings()
    database = Database(settings.database_url.get_secret_value(), 2)
    try:
        async with database.sessions() as db, db.begin():
            await db.execute(delete(User).where(User.id == UUID(sys.stdin.read().strip())))
    finally:
        await database.close()
asyncio.run(remove())
"""
            compose(
                "exec",
                "-T",
                "user-service",
                "/app/.venv/bin/python",
                "-c",
                cleanup,
                input_text=user_id,
            )

    def test_staff_login_rate_limit(self) -> None:
        # A container source IP avoids throttling the user's browser after this test.
        probe = """
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen
statuses = []
for _ in range(15):
    request = Request('http://proxy:8080/api/v1/users/auth/staff', data=b'{}',
                      headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urlopen(request, timeout=5) as response:
            statuses.append(response.status)
    except HTTPError as error:
        statuses.append(error.code)
        error.close()
print(json.dumps(statuses))
"""
        result = compose("exec", "-T", "user-service", "/app/.venv/bin/python", "-c", probe)
        self.assertIn(429, json.loads(result.stdout))

    def test_order_creation_lifecycle_and_outbox(self) -> None:
        login = "orders-" + uuid4().hex
        password = secrets.token_urlsafe(32)
        provision = """
import asyncio, json, sys
from user_service.cli import provision_staff
from user_service.config import Settings
from user_service.domain.users import Role
from user_service.infrastructure.database import Database
from user_service.infrastructure.models import User
from user_service.infrastructure.signing import TokenIssuer
async def prepare():
    value = json.load(sys.stdin)
    settings = Settings()
    admin_id = await provision_staff(value['login'], 'Order Smoke Admin', Role.ADMIN,
                                     value['password'], settings)
    database = Database(settings.database_url.get_secret_value(), 2)
    try:
        async with database.sessions() as db, db.begin():
            user = User(full_name='Order Smoke Client', role=Role.CLIENT)
            db.add(user)
            await db.flush()
            result = {'admin_id': admin_id, 'client_id': str(user.id),
                      'token': TokenIssuer(settings).issue(user.id, Role.CLIENT)}
        print(json.dumps(result))
    finally:
        await database.close()
asyncio.run(prepare())
"""
        fixture = json.loads(
            compose(
                "exec",
                "-T",
                "user-service",
                "/app/.venv/bin/python",
                "-c",
                provision,
                input_text=json.dumps({"login": login, "password": password}),
            ).stdout
        )
        admin_headers: dict[str, str] = {}
        client_headers = {"Authorization": "Bearer " + fixture["token"]}
        category_id = item_id = slot_id = None

        def request(
            method: str, path: str, body: object = None, headers: dict[str, str] | None = None
        ) -> tuple[int, object]:
            value = Request(
                self.mini + path,
                method=method,
                headers={"Content-Type": "application/json", **(headers or {})},
                data=None if body is None else json.dumps(body).encode(),
            )
            try:
                response = urlopen(value, timeout=15)
            except HTTPError as error:
                response = error
            with response:
                content = response.read()
                return response.status, json.loads(content) if content else None

        try:
            status, value = request(
                "POST", "/api/v1/users/auth/staff", {"username": login, "password": password}
            )
            self.assertEqual(status, 200)
            admin_headers["Authorization"] = "Bearer " + value["access_token"]
            status, value = request(
                "POST", "/api/v1/menu/categories", {"name": login}, admin_headers
            )
            self.assertEqual(status, 201)
            category_id = value["id"]
            item_body = {"category_id": category_id, "name": login, "price": 12000}
            status, value = request("POST", "/api/v1/menu/items", item_body, admin_headers)
            self.assertEqual(status, 201)
            item_id = value["id"]
            start = datetime.now(UTC) + timedelta(hours=1)
            status, value = request(
                "POST",
                "/api/v1/orders/slots",
                {
                    "start_time": start.isoformat(),
                    "end_time": (start + timedelta(minutes=10)).isoformat(),
                    "capacity": 1,
                },
                admin_headers,
            )
            self.assertEqual(status, 201)
            slot_id = value["id"]
            body = {
                "slot_id": slot_id,
                "items": [{"menu_item_id": item_id, "quantity": 1}],
                "expected_total_amount": 12000,
            }
            first_headers = {**client_headers, "Idempotency-Key": str(uuid4())}
            status, first = request("POST", "/api/v1/orders", body, first_headers)
            self.assertEqual(status, 201)
            self.assertEqual(first["total_amount"], 12000)
            self.assertEqual(request("POST", "/api/v1/orders", body, first_headers)[1], first)
            status, _ = request(
                "PUT", f"/api/v1/menu/items/{item_id}", {**item_body, "price": 15000}, admin_headers
            )
            self.assertEqual(status, 200)
            status, history = request(
                "GET", f"/api/v1/orders/{first['id']}", headers=client_headers
            )
            self.assertEqual(status, 200)
            self.assertEqual(history["items"][0]["price_at_moment"], 12000)
            second_headers = {**client_headers, "Idempotency-Key": str(uuid4())}
            status, changed = request("POST", "/api/v1/orders/", body, second_headers)
            self.assertEqual(status, 409)
            self.assertEqual(changed["detail"]["code"], "PRICE_CHANGED")
            status, cancelled = request(
                "POST",
                f"/api/v1/orders/{first['id']}/cancel",
                {"expected_version": 1},
                client_headers,
            )
            self.assertEqual(status, 200)
            self.assertEqual(cancelled["status"], "CANCELLED")
            self.assertEqual(request("POST", "/api/v1/orders", body, first_headers)[1], first)
            status, second = request(
                "POST", "/api/v1/orders", {**body, "expected_total_amount": 15000}, second_headers
            )
            self.assertEqual(status, 201)
            for version, target in [(1, "PREPARING"), (2, "READY"), (3, "COMPLETED")]:
                status, result = request(
                    "PATCH",
                    f"/api/v1/orders/{second['id']}/status",
                    {"expected_version": version, "status": target},
                    admin_headers,
                )
                self.assertEqual(status, 200)
                self.assertEqual(result["version"], version + 1)
            self.assertEqual(
                request("GET", "/api/v1/orders", headers=client_headers)[1]["total"], 2
            )
            with urlopen(self.mini + "/api/v1/orders/openapi.json", timeout=10) as response:
                self.assertIn("/slots", json.load(response)["paths"])
            inspect = """
import asyncio, json, sys
from uuid import UUID
from sqlalchemy import select
from order_service.config import Settings
from order_service.infrastructure.database import Database
from order_service.infrastructure.models import Order, OutboxEvent
async def inspect():
    settings = Settings()
    database = Database(settings.database_url.get_secret_value(), 2)
    try:
        async with database.sessions() as db:
            ids = select(Order.id).where(Order.user_id == UUID(sys.stdin.read().strip()))
            rows = list(await db.scalars(
                select(OutboxEvent).where(OutboxEvent.aggregate_id.in_(ids))))
            print(json.dumps({'count': len(rows),
                              'pending': all(row.published_at is None for row in rows),
                              'types': [row.event_type for row in rows]}))
    finally:
        await database.close()
asyncio.run(inspect())
"""
            events = json.loads(
                compose(
                    "exec",
                    "-T",
                    "order-service",
                    "/app/.venv/bin/python",
                    "-c",
                    inspect,
                    input_text=fixture["client_id"],
                ).stdout
            )
            self.assertEqual(events["count"], 6)
            self.assertTrue(events["pending"])
            self.assertEqual(events["types"].count("ORDER_CANCELLED"), 1)
        finally:
            cleanup_orders = """
import asyncio, json, sys
from uuid import UUID
from sqlalchemy import delete, select, text
from order_service.config import Settings
from order_service.infrastructure.database import Database
from order_service.infrastructure.models import IdempotencyRecord, Order, OutboxEvent
async def remove():
    settings = Settings()
    database = Database(settings.database_url.get_secret_value(), 2)
    fixture = json.load(sys.stdin)
    user_id = UUID(fixture["client_id"])
    try:
        async with database.sessions() as db, db.begin():
            ids = select(Order.id).where(Order.user_id == user_id)
            await db.execute(delete(IdempotencyRecord).where(IdempotencyRecord.user_id == user_id))
            await db.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id.in_(ids)))
            await db.execute(delete(Order).where(Order.user_id == user_id))
            if fixture['slot_id']:
                await db.execute(text("UPDATE time_slots SET current_orders=(SELECT count(*) "
                    "FROM orders WHERE slot_id=:slot_id AND status<>'CANCELLED') "
                    "WHERE id=:slot_id"),
                    {'slot_id': UUID(fixture['slot_id'])})
    finally:
        await database.close()
asyncio.run(remove())
"""
            compose(
                "exec",
                "-T",
                "order-service",
                "/app/.venv/bin/python",
                "-c",
                cleanup_orders,
                input_text=json.dumps({"client_id": fixture["client_id"], "slot_id": slot_id}),
            )
            if slot_id:
                request("DELETE", f"/api/v1/orders/slots/{slot_id}", headers=admin_headers)
            if item_id:
                request("DELETE", f"/api/v1/menu/items/{item_id}", headers=admin_headers)
            if category_id:
                request("DELETE", f"/api/v1/menu/categories/{category_id}", headers=admin_headers)
            cleanup_users = """
import asyncio, json, sys
from uuid import UUID
from sqlalchemy import delete
from user_service.config import Settings
from user_service.infrastructure.database import Database
from user_service.infrastructure.models import User
async def remove():
    settings = Settings()
    database = Database(settings.database_url.get_secret_value(), 2)
    ids = [UUID(value) for value in json.load(sys.stdin)]
    try:
        async with database.sessions() as db, db.begin():
            await db.execute(delete(User).where(User.id.in_(ids)))
    finally:
        await database.close()
asyncio.run(remove())
"""
            compose(
                "exec",
                "-T",
                "user-service",
                "/app/.venv/bin/python",
                "-c",
                cleanup_users,
                input_text=json.dumps([fixture["admin_id"], fixture["client_id"]]),
            )


if __name__ == "__main__":
    unittest.main()
