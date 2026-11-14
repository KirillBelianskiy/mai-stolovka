"""Exercise MAI Food's local API journey with new, disposable Compose state."""

import argparse
import base64
import hashlib
import hmac
import json
import os
import secrets
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from mvp_preflight import NoRedirect
from mvp_preflight import run as preflight

ROOT = Path(__file__).resolve().parents[2]
ORDERS = "/api/v1/orders"
USERS = "/api/v1/users"
MENU = "/api/v1/menu"
PRICE = 12000
CREDIT = 50000
SERVICES = (
    "postgres",
    "kafka",
    "user-service",
    "menu-service",
    "order-service",
    "notification-service",
    "websocket-service",
    "telegram-mini-app",
    "kitchen-app",
    "proxy",
)
DATABASE_SERVICES = ("user-service", "menu-service", "order-service", "notification-service")

PROVISION = """
import asyncio
import json
import sys

from user_service.cli import provision_staff
from user_service.config import Settings
from user_service.domain.users import Role

async def main():
    fixtures = json.load(sys.stdin)
    for role, fixture in fixtures.items():
        await provision_staff(fixture["username"], "Acceptance " + role, Role(role),
                              fixture["password"], Settings())

asyncio.run(main())
"""

# Read only synthetic rows through the Order container and its own database role.
INSPECT = """
import asyncio
import json
import sys
from uuid import UUID

from sqlalchemy import select
from order_service.config import Settings
from order_service.infrastructure.database import Database
from order_service.infrastructure.models import DemoLedger, DemoWallet, Order, OutboxEvent, TimeSlot

async def main():
    fixture = json.load(sys.stdin)
    user_id, slot_id = UUID(fixture["user"]), UUID(fixture["slot"])
    settings = Settings()
    database = Database(settings.database_url.get_secret_value(), 2)
    try:
        async with database.sessions() as db:
            orders = list(await db.scalars(select(Order).where(Order.user_id == user_id)))
            ledger = await db.execute(
                select(DemoLedger.kind, DemoLedger.amount).where(DemoLedger.user_id == user_id)
            )
            events = await db.execute(
                select(OutboxEvent.aggregate_version, OutboxEvent.event_type)
                .where(OutboxEvent.aggregate_id.in_([order.id for order in orders]))
            )
            print(json.dumps({
                "orders": sorted(
                    [str(o.id), o.status, o.version, o.payment_status] for o in orders
                ),
                "ledger": sorted(list(row) for row in ledger),
                "events": sorted(list(row) for row in events),
                "balance": (await db.get(DemoWallet, user_id)).balance,
                "capacity_used": (await db.get(TimeSlot, slot_id)).current_orders,
            }))
    finally:
        await database.close()

asyncio.run(main())
"""


class CheckFailure(Exception):
    """A safe diagnostic carrying no request body or credentials."""


def require(condition, label):
    if not condition:
        raise CheckFailure(label)


def launch_data(token, user_id):
    if not token.startswith("local-acceptance:"):
        raise ValueError("Only a generated acceptance signing key is supported")
    fields = {
        "auth_date": str(int(datetime.now(UTC).timestamp())),
        "user": json.dumps({"id": user_id, "first_name": "Acceptance Fixture"}),
    }
    secret = hmac.digest(b"WebAppData", token.encode(), hashlib.sha256)
    canonical = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    fields["hash"] = hmac.new(secret, canonical.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def verify_checkout_pair(replies):
    (first, first_flag), (second, second_flag) = replies
    require({first_flag, second_flag} == {"true", "false"}, "expected one original and one replay")
    require(first == second, "original/replay order snapshots differ")
    return first


def command(args, *, input_text=None, env=None, timeout=60):
    result = subprocess.run(
        args, cwd=ROOT, input=input_text, capture_output=True, text=True, env=env, timeout=timeout
    )
    if result.returncode:
        raise CheckFailure(f"command exited {result.returncode}")
    return result.stdout.strip()


def local_ports():
    sockets = [socket.socket() for _ in range(4)]
    try:
        for listener in sockets:
            listener.bind(("127.0.0.1", 0))
        return [listener.getsockname()[1] for listener in sockets]
    finally:
        for listener in sockets:
            listener.close()


class Stack:
    def __init__(self, env_file):
        self.name = "mai-accept-" + uuid4().hex[:16]
        self.token = "local-acceptance:" + secrets.token_hex(32)
        pg, kafka, mini, staff = local_ports()
        self.customer = f"http://127.0.0.1:{mini}"
        self.staff = f"http://127.0.0.1:{staff}"
        private = command(
            ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072"]
        )
        public = command(["openssl", "pkey", "-pubout"], input_text=private + "\n")
        settings = {
            key: secrets.token_hex(24)
            for key in (
                "POSTGRES_PASSWORD",
                "USERS_DB_PASSWORD",
                "MENU_DB_PASSWORD",
                "ORDERS_DB_PASSWORD",
                "NOTIFICATIONS_DB_PASSWORD",
            )
        }
        settings.update(
            POSTGRES_PORT=str(pg),
            KAFKA_PORT=str(kafka),
            MINI_APP_PORT=str(mini),
            KITCHEN_APP_PORT=str(staff),
            ORDER_DEMO_PAYMENTS_ENABLED="true",
            JWT_PRIVATE_KEY_BASE64=base64.b64encode((private + "\n").encode()).decode(),
            JWT_PUBLIC_KEY_BASE64=base64.b64encode((public + "\n").encode()).decode(),
            TELEGRAM_BOT_TOKEN=self.token,
            NOTIFICATION_SERVICE_PUBLIC_KEY_BASE64="",
            TELEGRAM_WEBHOOK_SECRET="",
        )
        env_file.write_text("".join(f"{key}={value}\n" for key, value in settings.items()))
        self.env = {
            key: value
            for key, value in os.environ.items()
            if key not in settings and not key.startswith(("COMPOSE_", "DOCKER_"))
        }
        docker = ["docker"]
        context = command(docker + ["context", "show"], env=self.env)
        endpoint = command(
            docker + ["context", "inspect", context, "--format", "{{.Endpoints.docker.Host}}"],
            env=self.env,
        )
        require(endpoint.startswith("unix://"), "Docker must target a local Unix socket")
        self.overlay = env_file.with_name("acceptance-origins.json")
        self.compose = docker + [
            "--context",
            context,
            "compose",
            "--project-name",
            self.name,
            "--env-file",
            str(env_file),
            "-f",
            "docker-compose.yml",
            "-f",
            "compose.local-demo.yml",
        ]

    def run(self, *args, input_text=None, timeout=60):
        return command(
            self.compose + list(args), input_text=input_text, env=self.env, timeout=timeout
        )

    def python(self, service, program, fixture):
        return self.run(
            "exec",
            "-T",
            service,
            "/app/.venv/bin/python",
            "-c",
            program,
            input_text=json.dumps(fixture),
        )

    def configure(self):
        # Override the demonstration's fixed browser origins for this disposable project.
        origins = f"{self.customer},{self.staff}"
        self.overlay.write_text(
            json.dumps(
                {
                    "services": {
                        "user-service": {
                            "environment": {"APP_SESSION_COOKIE_ALLOWED_ORIGINS": origins}
                        },
                        "websocket-service": {"environment": {"APP_ALLOWED_ORIGINS": self.staff}},
                    }
                }
            )
        )
        self.compose += ["-f", str(self.overlay)]
        config = json.loads(self.run("config", "--format", "json"))
        expected = {
            (8080, self.customer.rsplit(":", 1)[1]),
            (8081, self.staff.rsplit(":", 1)[1]),
        }
        actual = {
            (p["target"], str(p["published"]))
            for p in config["services"]["proxy"]["ports"]
            if p.get("host_ip") == "127.0.0.1"
        }
        require(actual == expected, "proxy mapping differs from assigned loopback ports")

    def build(self):
        self.run("build", *SERVICES, timeout=900)

    def start(self):
        self.run(
            "up", "-d", "--no-build", "--wait", "--wait-timeout", "300", *SERVICES, timeout=330
        )

    def migrate(self):
        versions = {}
        for service in DATABASE_SERVICES:
            self.run(
                "exec", "-T", service, "/app/.venv/bin/alembic", "upgrade", "head", timeout=120
            )
            versions[service] = self.run("exec", "-T", service, "/app/.venv/bin/alembic", "current")
        return versions

    def image_ids(self):
        containers = self.run("ps", "-q", *SERVICES).splitlines()
        require(len(containers) == len(SERVICES), "missing acceptance container")
        return dict(
            line.split(maxsplit=1)
            for line in command(
                self.compose[:3]
                + [
                    "inspect",
                    "--format",
                    '{{index .Config.Labels "com.docker.compose.service"}} {{.Image}}',
                    *containers,
                ],
                env=self.env,
            ).splitlines()
        )


class Journey:
    def __init__(self, stack, report):
        self.stack = stack
        self.report = report
        self.tokens = {}

    def http(self, method, path, expected, role=None, body=None, key=None, *, staff=False):
        origin = self.stack.staff if staff else self.stack.customer
        headers = {"Content-Type": "application/json", "Origin": origin}
        if role:
            headers["Authorization"] = "Bearer " + self.tokens[role]
        if key:
            headers["Idempotency-Key"] = key
        request = Request(
            origin + path,
            method=method,
            headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        try:
            response = build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            label = f"{method} {path.split('?')[0]} ({role or 'anonymous'})"
            require(
                response.status == expected, f"{label}: expected {expected}, got {response.status}"
            )
            data = response.read(1_048_577)
            require(len(data) <= 1_048_576, f"{label}: response too large")
            return (json.loads(data) if data else None), response.headers.get(
                "Idempotency-Replayed"
            )

    def login(self):
        fixtures = {
            role: {"username": f"accept-{role.lower()}", "password": secrets.token_urlsafe(24)}
            for role in ("ADMIN", "COOK", "CASHIER")
        }
        self.stack.python("user-service", PROVISION, fixtures)
        for role, credentials in fixtures.items():
            session, _ = self.http("POST", f"{USERS}/auth/staff", 200, body=credentials, staff=True)
            require(session["user"]["role"] == role, "wrong staff role")
            self.tokens[role] = session["access_token"]
        for role, identity in (("CLIENT_A", 900001), ("CLIENT_B", 900002)):
            session, _ = self.http(
                "POST",
                f"{USERS}/auth/telegram",
                200,
                body={"init_data": launch_data(self.stack.token, identity)},
            )
            require(session["user"]["role"] == "CLIENT", "wrong customer role")
            self.tokens[role] = session["access_token"]
            self.report["fixtures"][role] = session["user"]["id"]

    def seed(self):
        category, _ = self.http(
            "POST", f"{MENU}/categories", 201, "ADMIN", {"name": "Acceptance category"}, staff=True
        )
        item, _ = self.http(
            "POST",
            f"{MENU}/items",
            201,
            "ADMIN",
            {"category_id": category["id"], "name": "Acceptance item", "price": PRICE},
            staff=True,
        )
        start = datetime.now(UTC) + timedelta(hours=2)
        slot, _ = self.http(
            "POST",
            f"{ORDERS}/slots",
            201,
            "ADMIN",
            {
                "start_time": start.isoformat(),
                "end_time": (start + timedelta(minutes=20)).isoformat(),
                "capacity": 1,
            },
            staff=True,
        )
        self.report["fixtures"].update(item=item["id"], slot=slot["id"])
        self.cart = {
            "slot_id": slot["id"],
            "items": [{"menu_item_id": item["id"], "quantity": 1}],
            "expected_total_amount": PRICE,
        }

    def wallet(self, amount):
        balance, _ = self.http("GET", f"{ORDERS}/wallet", 200, "CLIENT_A")
        require(balance["checkout_payment_enabled"] is True, "demo wallet disabled")
        require(balance["balance"] == amount, f"unexpected wallet balance (expected {amount})")

    def checkout(self, key, *, expected=201, cart=None):
        return self.http("POST", f"{ORDERS}/", expected, "CLIENT_A", cart or self.cart, key)

    def credit(self):
        self.wallet(0)
        rejected, _ = self.checkout(str(uuid4()), expected=409)
        require(rejected["detail"]["code"] == "INSUFFICIENT_FUNDS", "wrong balance rejection")
        self.wallet(0)
        credit = {"user_id": self.report["fixtures"]["CLIENT_A"], "amount": CREDIT}
        key = str(uuid4())
        for role in ("CLIENT_A", "COOK", "CASHIER"):
            self.http("POST", f"{ORDERS}/wallet/credits", 403, role, credit, key, staff=True)
        replies = [
            self.http("POST", f"{ORDERS}/wallet/credits", 201, "ADMIN", credit, key, staff=True)
            for _ in range(2)
        ]
        verify_checkout_pair(replies)
        self.http(
            "POST",
            f"{ORDERS}/wallet/credits",
            409,
            "ADMIN",
            {**credit, "amount": CREDIT + 1},
            key,
            staff=True,
        )
        self.wallet(CREDIT)

    def duplicates_and_refund(self):
        key = str(uuid4())
        with ThreadPoolExecutor(max_workers=2) as pool:
            order = verify_checkout_pair(list(pool.map(self.checkout, (key, key))))
        require(
            order["payment_status"] == "DEMO_PAID" and order["total_amount"] == PRICE,
            "checkout lacks expected debit evidence",
        )
        self.report["fixtures"]["cancelled_order"] = order["id"]
        self.wallet(CREDIT - PRICE)
        detail = f"{ORDERS}/{order['id']}"
        self.http("GET", detail, 404, "CLIENT_B")
        cancel = {"expected_version": order["version"]}
        self.http("POST", detail + "/cancel", 404, "CLIENT_B", cancel)
        self.http("POST", detail + "/cancel", 403, "COOK", cancel, staff=True)
        self.http("POST", detail + "/cancel", 403, "CASHIER", cancel, staff=True)

        def cancel_order():
            return self.http("POST", detail + "/cancel", 200, "CLIENT_A", cancel)[0]

        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = [
                future.result() for future in (pool.submit(cancel_order), pool.submit(cancel_order))
            ]
        require(
            first == second
            and first["status"] == "CANCELLED"
            and first["payment_status"] == "DEMO_REFUNDED"
            and first["version"] == 2,
            "cancellation is not a stable single refund",
        )
        self.wallet(CREDIT)
        require(self.checkout(key) == (order, "true"), "original checkout replay changed")
        current, _ = self.http("GET", detail, 200, "CLIENT_A")
        require(current == first, "order detail differs from committed cancellation")
        self.snapshot(
            [[order["id"], "CANCELLED", 2, "DEMO_REFUNDED"]],
            [[1, "ORDER_CREATED"], [2, "ORDER_CANCELLED"]],
            [["CREDIT", CREDIT], ["DEBIT", PRICE], ["REFUND", PRICE]],
            CREDIT,
            0,
        )

    def staff_flow(self):
        order, _ = self.checkout(str(uuid4()))
        self.report["fixtures"]["completed_order"] = order["id"]
        path = f"{ORDERS}/{order['id']}"
        queue, _ = self.http(
            "GET", f"{ORDERS}/?status=PENDING&slot_id={order['slot_id']}", 200, "COOK", staff=True
        )
        require([row["id"] for row in queue["items"]] == [order["id"]], "staff queue lost order")
        preparing = {"status": "PREPARING", "expected_version": 1}
        self.http("PATCH", path + "/status", 403, "CASHIER", preparing, staff=True)
        for previous, status, role in (
            (1, "PREPARING", "COOK"),
            (2, "READY", "COOK"),
            (3, "COMPLETED", "CASHIER"),
        ):
            body = {"status": status, "expected_version": previous}
            if status == "COMPLETED":
                self.http("POST", path + "/cancel", 409, "CLIENT_A", {"expected_version": 3})
                self.http("PATCH", path + "/status", 403, "COOK", body, staff=True)
            current, _ = self.http("PATCH", path + "/status", 200, role, body, staff=True)
            require(
                current["status"] == status and current["version"] == previous + 1,
                "unexpected staff lifecycle state or version",
            )
            self.http("PATCH", path + "/status", 409, role, body, staff=True)
        self.http("POST", path + "/cancel", 409, "CLIENT_A", {"expected_version": 4})
        history, _ = self.http("GET", f"{ORDERS}/", 200, "CLIENT_B")
        require(history["total"] == 0, "foreign customer history is exposed")
        self.wallet(CREDIT - PRICE)
        self.snapshot(
            [
                [self.report["fixtures"]["cancelled_order"], "CANCELLED", 2, "DEMO_REFUNDED"],
                [order["id"], "COMPLETED", 4, "DEMO_PAID"],
            ],
            [[1, "ORDER_CREATED"], [2, "ORDER_CANCELLED"], [1, "ORDER_CREATED"]]
            + [[version, "ORDER_STATUS_UPDATED"] for version in (2, 3, 4)],
            [["CREDIT", CREDIT], ["DEBIT", PRICE], ["DEBIT", PRICE], ["REFUND", PRICE]],
            CREDIT - PRICE,
            1,
        )

    def snapshot(self, orders, events, ledger, balance, used):
        fixtures = self.report["fixtures"]
        actual = json.loads(
            self.stack.python(
                "order-service", INSPECT, {"user": fixtures["CLIENT_A"], "slot": fixtures["slot"]}
            )
        )
        self.report["database_observations"].append(actual)
        require(
            actual
            == {
                "orders": sorted(orders),
                "events": sorted(events),
                "ledger": sorted(ledger),
                "balance": balance,
                "capacity_used": used,
            },
            "order/slot/wallet/ledger/Outbox state differs from expected synthetic invariants",
        )


def run(output):
    report = {
        "started_utc": datetime.now(UTC).isoformat(),
        "scope": "local synthetic API acceptance",
        "full_journey_acceptance": "not_run",
        "checks": [],
        "fixtures": {},
        "database_observations": [],
    }
    stack = None
    cleanup_needed = False
    stage = "source identity"
    try:
        require(not command(["git", "status", "--porcelain"]), "run from a clean checkout")
        report["source_revision"] = command(["git", "rev-parse", "HEAD"])
        with TemporaryDirectory(prefix="mai-acceptance-") as tmp:
            try:
                stage = "configure isolated stack"
                stack = Stack(Path(tmp) / "synthetic.env")
                report["compose_project"] = stack.name
                stack.configure()
                journey = Journey(stack, report)
                stages = {
                    "build images": stack.build,
                    "start disposable stack": stack.start,
                    "migrate databases": stack.migrate,
                    "image identity": stack.image_ids,
                    "anonymous preflight": lambda: preflight(stack.customer, stack.staff),
                    "synthetic customer and staff authentication": journey.login,
                    "menu and future slot fixtures": journey.seed,
                    "balance rejection and idempotent ADMIN credit": journey.credit,
                    "concurrent duplicate checkout and refund": journey.duplicates_and_refund,
                    "COOK preparation and CASHIER issuance": journey.staff_flow,
                }
                for stage, check in stages.items():
                    print(stage, flush=True)
                    cleanup_needed |= stage == "start disposable stack"
                    observed = check()
                    if stage == "anonymous preflight":
                        require(observed["preflight_passed"], "anonymous route preflight failed")
                    result = {"stage": stage, "status": "pass"}
                    if observed is not None:
                        result["observed"] = observed
                    report["checks"].append(result)
            finally:
                if cleanup_needed:
                    try:
                        stack.run("down", "--volumes", "--remove-orphans", timeout=120)
                        report["cleanup"] = "pass"
                    except (CheckFailure, OSError, subprocess.TimeoutExpired):
                        report["cleanup"] = "failed"
    except (
        CheckFailure,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.TimeoutExpired,
    ) as err:
        report["checks"].append(
            {
                "stage": stage,
                "status": "fail",
                "reason": str(err) if isinstance(err, CheckFailure) else type(err).__name__,
            }
        )
    passed = report.get("cleanup") == "pass" and all(
        row["status"] == "pass" for row in report["checks"]
    )
    report["local_api_passed"] = passed
    report["finished_utc"] = datetime.now(UTC).isoformat()
    json.dump(report, output, indent=2)
    output.write("\n")
    print("Local API acceptance passed." if passed else "Local API acceptance failed. See report.")
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", required=True, type=Path, help="New JSON report outside checkout"
    )
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(ROOT):
        parser.error("write run evidence outside the checkout, then review before committing it")
    try:
        with args.output.open("x", encoding="utf-8") as output:
            return run(output)
    except OSError:
        parser.exit(2, "Could not create the requested report file.\n")


if __name__ == "__main__":
    raise SystemExit(main())
