"""Exercise the isolated staging listeners using synthetic accounts."""

import hashlib
import hmac
import http.client
import importlib.util
import json
import secrets
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[2]
CUSTOMER = 18280
KITCHEN = 18281
WEBHOOK = "/api/v1/users/internal/v1/telegram/webhook"
WS = "/api/v1/ws/kitchen"
CHECKS = 0


def request(port, method, path, expected, body=None, **headers):
    global CHECKS
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=8)
    try:
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        if response.status != expected:
            raise SystemExit(f"{port} {method} {path}: expected {expected}, got {response.status}")
        CHECKS += 1
        return response.read(), response.headers
    finally:
        connection.close()


def identity(token):
    fields = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": 883000002, "first_name": "Synthetic", "last_name": "Staging"}),
    }
    key = hmac.digest(b"WebAppData", token.encode(), hashlib.sha256)
    message = "\n".join(f"{name}={value}" for name, value in sorted(fields.items()))
    fields["hash"] = hmac.new(key, message.encode(), hashlib.sha256).hexdigest()
    return {"init_data": urlencode(fields)}


def check_customer(fields):
    origin = {"Origin": f"http://localhost:{CUSTOMER}"}
    body = identity(fields["TELEGRAM_BOT_TOKEN"])
    auth = "/api/v1/users/auth"
    request(CUSTOMER, "POST", f"{auth}/telegram", 403, body, Origin="https://other.invalid")
    data, headers = request(CUSTOMER, "POST", f"{auth}/telegram", 200, body, **origin)
    cookie = headers["Set-Cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie
    session = {"Cookie": cookie.split(";", 1)[0], **origin}
    account = json.loads(data)
    bearer = {"Authorization": f"Bearer {account['access_token']}"}
    request(CUSTOMER, "POST", f"{auth}/session", 200, **session)
    request(CUSTOMER, "GET", "/api/v1/users/me", 200, **bearer)
    request(CUSTOMER, "GET", "/api/v1/orders/?limit=1", 200, **bearer)
    request(CUSTOMER, "GET", "/api/v1/orders/wallet", 200, **bearer)
    request(CUSTOMER, "POST", f"{auth}/logout", 204, **session)
    request(CUSTOMER, "POST", f"{auth}/session", 401, **session)


def check_staff():
    # Create a synthetic account via the existing User provisioning function.
    spec = importlib.util.spec_from_file_location("staging", ROOT / "infra/mac-staging.py")
    staging = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(staging)
    account = {
        "username": "staging-smoke-" + secrets.token_hex(5),
        "password": secrets.token_urlsafe(24),
    }
    provision = """
import asyncio
import json
import sys
from user_service.cli import provision_staff
from user_service.config import Settings
from user_service.domain.users import Role
account = json.load(sys.stdin)
asyncio.run(provision_staff(
    account["username"], "Synthetic Staging Staff", Role.ADMIN, account["password"], Settings()
))
"""
    staging.compose(
        "exec",
        "-T",
        "user-service",
        "/app/.venv/bin/python",
        "-c",
        provision,
        input=json.dumps(account),
        text=True,
        stdout=subprocess.DEVNULL,
    )
    data, _ = request(KITCHEN, "POST", "/api/v1/users/auth/staff", 200, account)
    bearer = {"Authorization": f"Bearer {json.loads(data)['access_token']}"}
    spoofed = {"X-MAI-Public-API": "1", "X-Forwarded-For": "192.0.2.1", **bearer}
    request(KITCHEN, "GET", "/api/v1/orders/", 200, **spoofed)
    request(KITCHEN, "GET", "/api/v1/menu/admin/items", 200, **bearer)
    request(KITCHEN, "GET", "/api/v1/users/me", 200, **bearer)
    for path in ("/api/v1/orders/", "/api/v1/orders/wallet", "/api/v1/users/me"):
        request(CUSTOMER, "GET", path, 403, **{"X-MAI-Public-API": "0", **bearer})


def main():
    fields = dict(
        line.split("=", 1)
        for line in (ROOT / ".private/mac-staging/staging.env").read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    if not fields["TELEGRAM_BOT_TOKEN"].startswith("local-staging:"):
        raise SystemExit("Run this smoke test with a synthetic staging bot token")
    for port in (CUSTOMER, KITCHEN):
        request(port, "GET", "/", 200)
        request(port, "GET", "/api/v1/menu/items", 200)
        request(port, "GET", "/api/v1/users/docs", 404)
        request(port, "GET", "/api/v1/users/internal/v1/notification-recipients/123", 404)
    request(CUSTOMER, "GET", "/design/dishes/syrniki.jpg", 200)
    for method, path in (
        ("POST", "/api/v1/users/auth/staff"),
        ("POST", "/api/v1/orders/wallet/credits"),
        ("PATCH", "/api/v1/orders/00000000-0000-0000-0000-000000000000/status"),
        ("POST", "/api/v1/menu/items"),
        ("GET", "/api/v1/menu/admin/items"),
        ("GET", "/api/v1/menu/%69tems"),
        ("GET", "/api/v1/menu//items"),
        ("GET", "/api/v1/menu/../menu/items"),
        ("GET", WS),
    ):
        request(CUSTOMER, method, path, 404)
    request(CUSTOMER, "GET", "/api/v1/orders/", 401, **{"X-MAI-Public-API": "0"})
    request(
        KITCHEN,
        "POST",
        "/api/v1/users/auth/staff",
        401,
        {"username": "not-provisioned", "password": "synthetic-test-password"},
    )
    request(KITCHEN, "GET", "/api/v1/orders/", 401)
    upgrade = {
        "Connection": "Upgrade",
        "Upgrade": "websocket",
        "Sec-WebSocket-Version": "13",
        "Sec-WebSocket-Key": "dGhlIHNhbXBsZSBub25jZQ==",
    }
    request(KITCHEN, "GET", WS, 403, Origin="https://other.invalid", **upgrade)
    request(KITCHEN, "GET", WS, 101, Origin=f"http://localhost:{KITCHEN}", **upgrade)
    request(KITCHEN, "POST", WEBHOOK, 404, {"update_id": 1})
    request(CUSTOMER, "POST", WEBHOOK + "/", 404, {"update_id": 1})
    request(CUSTOMER, "POST", WEBHOOK + "?ignored=1", 404, {"update_id": 1})
    if fields["STAGING_WEBHOOK_ENABLED"] == "true":
        update = {"update_id": secrets.randbits(62)}
        request(CUSTOMER, "POST", WEBHOOK, 403, update)
        request(
            CUSTOMER, "POST", WEBHOOK, 403, update, **{"X-Telegram-Bot-Api-Secret-Token": "invalid"}
        )
        token = {"X-Telegram-Bot-Api-Secret-Token": fields["TELEGRAM_WEBHOOK_SECRET"]}
        request(CUSTOMER, "POST", WEBHOOK, 204, update, **token)
        request(CUSTOMER, "POST", WEBHOOK, 204, update, **token)
    else:
        request(CUSTOMER, "POST", WEBHOOK, 404, {"update_id": 1})
    check_customer(fields)
    check_staff()
    print(f"{CHECKS} staging HTTP and WebSocket checks passed")


if __name__ == "__main__":
    main()
