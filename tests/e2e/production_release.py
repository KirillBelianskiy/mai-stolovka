"""Disposable production-route gate: local TLS, synthetic identities, fake Telegram only."""

import argparse
import base64
import gzip
import http.client
import json
import secrets
import socket
import ssl
import struct
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import HTTPSHandler

import mvp_acceptance as acceptance

ROOT = acceptance.ROOT
WEBHOOK = "/api/v1/users/internal/v1/telegram/webhook"
CUSTOMER = "maistolovka.me"
KITCHEN = "kitchen.maistolovka.me"


class LoopbackHTTPS(http.client.HTTPSConnection):
    """Connect exclusively to loopback, with normal certificate and hostname verification."""

    def connect(self):
        sock = socket.create_connection(("127.0.0.1", self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class Stack(acceptance.Stack):
    def __init__(self, directory):
        super().__init__(directory / "synthetic.env")
        self.directory = directory
        self.port, self.http_port, _, _ = acceptance.local_ports()
        self.customer = f"https://{CUSTOMER}:{self.port}"
        self.staff = f"https://{KITCHEN}:{self.port}"
        self.context = ssl.create_default_context()
        self.secret = secrets.token_hex(24)
        private = (
            acceptance.command(
                ["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072"]
            )
            + "\n"
        )
        public = acceptance.command(["openssl", "pkey", "-pubout"], input_text=private) + "\n"
        env_file = directory / "synthetic.env"
        with env_file.open("a") as stream:
            stream.write("PROD_KITCHEN_CIDRS=172.16.0.0/12 192.168.0.0/16 127.0.0.1/32\n")
            stream.write("PROD_WEBHOOK_ENABLED=true\n")
            stream.write(
                f"NOTIFICATION_SIGNING_KEY_BASE64={base64.b64encode(private.encode()).decode()}\n"
            )
        # Replace existing empty values rather than creating duplicate env assignments.
        text = env_file.read_text().replace(
            "TELEGRAM_WEBHOOK_SECRET=\n", f"TELEGRAM_WEBHOOK_SECRET={self.secret}\n"
        )
        text = text.replace(
            "NOTIFICATION_SERVICE_PUBLIC_KEY_BASE64=\n",
            "NOTIFICATION_SERVICE_PUBLIC_KEY_BASE64="
            + base64.b64encode(public.encode()).decode()
            + "\n",
        )
        env_file.write_text(text)
        env_file.chmod(0o600)
        # Only TLS issuer changes; every production route is read directly from this checkout.
        source = (ROOT / "infra/production/Caddyfile").read_text()
        self.caddy = directory / "Caddyfile"
        self.caddy.write_text(
            source.replace("maistolovka.me {", "maistolovka.me {\n\ttls internal")
        )
        self.compose[-1] = "docker-compose.prod.yml"
        self.compose += ["--profile", "outbox", "--profile", "inbox", "--profile", "telegram"]
        overlay = directory / "production-test.yml"
        overlay.write_text(
            f"""services:
  edge:
    ports: !override
      - "127.0.0.1:{self.port}:443"
      - "127.0.0.1:{self.http_port}:80"
    volumes:
      - {self.caddy}:/etc/caddy/Caddyfile:ro
  user-service:
    environment:
      APP_SESSION_COOKIE_ALLOWED_ORIGINS: {self.customer}
  websocket-service:
    environment:
      APP_ALLOWED_ORIGINS: {self.staff}
  notification-dispatch:
    environment:
      APP_DISPATCH_BOT_MODE: fake
      APP_DISPATCH_BOT_TOKEN: !reset null
      APP_DISPATCH_FAKE_BOT_URL: http://fake-bot:8080
    depends_on:
      fake-bot:
        condition: service_started
  fake-bot:
    image: python:3.12.16-slim-bookworm
    command: [python, -u, /staging/fake_bot.py]
    volumes:
      - {ROOT / "infra/mac-staging/fake_bot.py"}:/staging/fake_bot.py:ro
volumes:
"""
            + "".join(
                f"  {name}:\n    external: false\n    name: {self.name}_{name}\n"
                for name in ("postgres-data", "kafka-data", "tls-data", "tls-config")
            )
        )
        self.compose += ["-f", str(overlay)]

    def configure(self):
        config = json.loads(self.run("config", "--format", "json"))
        acceptance.require(config["name"] == self.name, "wrong test project")
        for kind in ("volumes", "networks"):
            for resource in config.get(kind, {}).values():
                acceptance.require(
                    not resource.get("external") and resource["name"].startswith(self.name + "_"),
                    "external test resource",
                )
        ports = [
            (name, port)
            for name, service in config["services"].items()
            for port in service.get("ports", [])
        ]
        acceptance.require(
            len(ports) == 2
            and all(name == "edge" and port.get("host_ip") == "127.0.0.1" for name, port in ports),
            "non-loopback test listener",
        )
        acceptance.require(
            config["services"]["notification-dispatch"]["environment"]["APP_DISPATCH_BOT_MODE"]
            == "fake",
            "live Telegram dispatch forbidden",
        )
        acceptance.require(
            not config["services"]["notification-dispatch"]["environment"].get(
                "APP_DISPATCH_BOT_TOKEN"
            ),
            "dispatcher has a real credential",
        )
        self.run("config", "--quiet")

    def build(self):
        self.run("--parallel", "2", "build", timeout=1200)

    def start(self):
        self.run(
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
            timeout=60,
        )
        self.run("up", "-d", "--wait", "--wait-timeout", "240", "postgres", "kafka", timeout=270)
        versions = {}
        for service in acceptance.DATABASE_SERVICES:
            self.run(
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "/app/.venv/bin/alembic",
                service,
                "upgrade",
                "head",
                timeout=90,
            )
            versions[service] = self.run(
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "/app/.venv/bin/alembic",
                service,
                "current",
            )
        self.run(
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
        self.run("up", "-d", "--no-build", "--wait", "--wait-timeout", "240", timeout=270)
        ca = self.directory / "root.crt"
        self.run("cp", "edge:/data/caddy/pki/authorities/local/root.crt", str(ca))
        self.context.load_verify_locations(cafile=str(ca))
        original = acceptance.build_opener
        handler = HTTPSHandler(context=self.context)
        handler.https_open = lambda request: handler.do_open(
            LoopbackHTTPS, request, context=self.context
        )
        acceptance.build_opener = lambda *args: original(*args, handler)
        version = self.run("exec", "-T", "edge", "caddy", "version")
        modules = self.run("exec", "-T", "edge", "caddy", "list-modules", "--versions")
        acceptance.require(version.startswith("v2.11.9"), "Caddy version drift")
        acceptance.require("http.handlers.rate_limit v0.1.0" in modules, "limiter module drift")
        return {"migrations": versions, "caddy": version, "rate_limit_module": "v0.1.0"}

    def request(self, method, path, expected, *, staff=False, body=None, headers=None):
        host = KITCHEN if staff else CUSTOMER
        connection = LoopbackHTTPS(host, self.port, context=self.context, timeout=15)
        try:
            connection.request(
                method,
                path,
                json.dumps(body) if body is not None else None,
                {"Content-Type": "application/json", **(headers or {})},
            )
            response = connection.getresponse()
            payload = response.read()
            acceptance.require(
                response.status == expected,
                f"{method} {path.split('?')[0]}: expected {expected}, got {response.status}",
            )
            return payload, response.headers
        finally:
            connection.close()

    def recreate_edge(self):
        self.run("up", "-d", "--no-deps", "--force-recreate", "--wait", "edge", timeout=90)


class Journey(acceptance.Journey):
    def http(self, method, path, expected, role=None, body=None, key=None, *, staff=False):
        result = super().http(method, path, expected, role, body, key, staff=staff)
        if expected == 200 and method == "PATCH" and body and body.get("status") == "READY":
            self.delivery()
        return result

    def proxy_compatibility(self):
        """Replay baseline Nginx configuration against identical upstreams and exports."""
        stack = self.stack
        baseline = "f0202c1a1924415018236a7641df7a9623adf0f8"
        directory = stack.directory / "compatibility"
        directory.mkdir()
        nginx = directory / "nginx.conf"
        routes = directory / "api-routes.conf"
        static = directory / "static.conf"
        for target, source in (
            (nginx, "nginx.conf"),
            (routes, "api-routes.conf"),
            (static, "static.conf"),
        ):
            target.write_text(
                acceptance.command(["git", "show", f"{baseline}:infra/nginx/{source}"])
            )
        nginx.write_text(
            nginx.read_text()
            .replace("telegram-mini-app:80", "legacy-customer:80")
            .replace("kitchen-app:80", "legacy-kitchen:80")
        )
        exports = directory / "exports"
        exports.mkdir()
        for app in ("telegram-mini-app", "kitchen-app"):
            destination = exports / app
            destination.mkdir()
            stack.run("cp", f"{app}:/srv/.", str(destination))
        old_port, new_port, _, _ = acceptance.local_ports()
        overlay = directory / "comparison.json"
        overlay.write_text(
            json.dumps(
                {
                    "services": {
                        "proxy": {
                            "ports": [
                                {"target": 8080, "published": str(new_port), "host_ip": "127.0.0.1"}
                            ]
                        },
                        "legacy-proxy": {
                            "image": "nginx:1.30.6-alpine",
                            "ports": [f"127.0.0.1:{old_port}:8080"],
                            "volumes": [
                                f"{nginx}:/etc/nginx/nginx.conf:ro",
                                f"{routes}:/etc/nginx/api-routes.conf:ro",
                            ],
                        },
                        **{
                            name: {
                                "image": "nginx:1.30.6-alpine",
                                "volumes": [
                                    f"{static}:/etc/nginx/conf.d/default.conf:ro",
                                    f"{exports / app}:/usr/share/nginx/html:ro",
                                ],
                            }
                            for name, app in (
                                ("legacy-customer", "telegram-mini-app"),
                                ("legacy-kitchen", "kitchen-app"),
                            )
                        },
                    }
                }
            )
        )
        original = stack.compose[:]
        stack.compose += ["-f", str(overlay)]
        try:
            stack.run("build", "proxy", timeout=300)
            stack.run(
                "up",
                "-d",
                "--no-build",
                "--wait",
                "legacy-customer",
                "legacy-kitchen",
                "legacy-proxy",
                "proxy",
                timeout=120,
            )
            observations = []
            cases = [
                ("GET", "/"),
                ("HEAD", "/"),
                ("GET", "/design/dishes/syrniki.jpg"),
                ("GET", "/missing-static-file"),
                ("GET", "/api/unknown"),
                ("GET", "/api/v1/users"),
                ("GET", "/api/v1/menu"),
                ("GET", "/api/v1/users?preserve=1"),
                ("GET", "/api/v1/menu/categories?limit=1"),
                ("GET", "/api/v1/menu/items?limit=1&offset=0"),
                ("POST", "/api/v1/menu/items"),
                ("GET", "/api/v1/users/me"),
                ("GET", "/api/v1/orders"),
                ("GET", "/api/v1/orders/"),
                ("GET", "/api/v1/orders/slots"),
                ("GET", "/api/v1/orders/wallet"),
                ("GET", "/api/v1/orders/not-implemented/unknown"),
                ("GET", "/api/v1/users/internal/v1/notification-recipients/123"),
                ("POST", "/api/v1/users/auth/staff"),
            ]
            for method, path in cases:
                replies = []
                for port in (old_port, new_port):
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                    connection.request(method, path)
                    response = connection.getresponse()
                    body = response.read()
                    location = response.getheader("Location")
                    # Nginx uses an absolute Location; Caddy uses a relative Location.
                    if location:
                        from urllib.parse import urlsplit

                        parsed = urlsplit(location)
                        location = (parsed.path, parsed.query)
                    replies.append(
                        (response.status, body, location, response.getheader("Content-Type"))
                    )
                    connection.close()
                old, new = replies
                acceptance.require(
                    old[0] == new[0] and old[2] == new[2],
                    f"proxy status/redirect drift: {method} {path}",
                )
                if old[3] == "application/json" or old[0] == 200:
                    acceptance.require(old[1] == new[1], f"proxy body drift: {method} {path}")
                observations.append(
                    {
                        "method": method,
                        "path": path,
                        "status": new[0],
                        "body_equal": old[1] == new[1],
                    }
                )
            return observations
        finally:
            stack.run(
                "rm",
                "-s",
                "-f",
                "proxy",
                "legacy-proxy",
                "legacy-customer",
                "legacy-kitchen",
                timeout=60,
            )
            stack.compose = original

    def static_rollback(self):
        stack = self.stack
        artifacts = stack.directory / "compatibility/exports"
        old, new = "a" * 40, "b" * 40
        for revision in (old, new):
            for app in ("telegram-mini-app", "kitchen-app"):
                destination = artifacts / revision / app
                destination.mkdir(parents=True)
                (destination / "index.html").write_text(f"<html>{revision} {app}</html>")
        port, _, _, _ = acceptance.local_ports()
        overlay = stack.directory / "static-rollback.json"
        overlay.write_text(
            json.dumps(
                {
                    "services": {
                        "staging-ingress": {
                            "build": str(ROOT / "infra/caddy"),
                            "ports": [f"127.0.0.1:{port}:8080"],
                            "volumes": [
                                f"{ROOT / 'infra/mac-staging/Caddyfile'}:/etc/caddy/Caddyfile:ro",
                                f"{ROOT / 'infra/caddy/routes.caddy'}:/etc/caddy/routes.caddy:ro",
                                f"{artifacts}:/srv:ro",
                            ],
                            "environment": {"STAGING_ARTIFACT_REVISION": old},
                        }
                    }
                }
            )
        )
        original = stack.compose[:]
        stack.compose += ["-f", str(overlay)]
        try:
            stack.run("build", "staging-ingress", timeout=300)
            stack.run(
                "run",
                "--rm",
                "--no-deps",
                "staging-ingress",
                "caddy",
                "validate",
                "--config",
                "/etc/caddy/Caddyfile",
                "--adapter",
                "caddyfile",
            )
            for revision in (old, new, old):
                selection = stack.directory / "static-selection.json"
                selection.write_text(
                    json.dumps(
                        {
                            "services": {
                                "staging-ingress": {
                                    "environment": {"STAGING_ARTIFACT_REVISION": revision}
                                }
                            }
                        }
                    )
                )
                stack.compose += ["-f", str(selection)]
                stack.run(
                    "up", "-d", "--no-deps", "--force-recreate", "staging-ingress", timeout=60
                )
                deadline = time.monotonic() + 15
                while True:
                    try:
                        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                        connection.request("GET", "/")
                        response = connection.getresponse()
                        body = response.read().decode()
                        connection.close()
                        acceptance.require(
                            response.status == 200 and revision in body,
                            "static selection/rollback returned another artifact",
                        )
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise
                        time.sleep(0.2)
                stack.compose = stack.compose[:-2]
        finally:
            stack.run("rm", "-s", "-f", "staging-ingress", timeout=60)
            stack.compose = original

    def session_and_routes(self):
        stack = self.stack
        for staff in (False, True):
            for path in ("/", "/design/dishes/syrniki.jpg") if not staff else ("/",):
                stack.request("GET", path, 200, staff=staff)
            for path in (
                "/api",
                "/api/unknown",
                "/api/v1/users/docs",
                "/api/v1/users/internal/v1/notification-recipients",
                "/api/v1/users/internal/v1/notification-recipients/123",
                "/api/v1/users/internal/v1/notification-recipients/123/blocked",
                "/health/user/ready",
            ):
                for method in ("GET", "POST"):
                    stack.request(
                        method,
                        path,
                        404,
                        staff=staff,
                        headers={"X-Forwarded-For": "127.0.0.1", "X-MAI-Public-API": "0"},
                    )
        for path in (
            "/api/v1/menu/%69tems",
            "/api/v1/menu//items",
            "/api/v1/menu/../menu/items",
            "/api/v1/menu/items/",
            "/API/v1/menu/items",
        ):
            stack.request("GET", path, 404)
        stack.request("POST", "/api/v1/menu/items", 404)
        stack.request("GET", "/api/v1/orders/slots", 401)
        stack.request("GET", "/api/v1/menu/items?limit=1&offset=0", 200)
        payload, headers = stack.request("GET", "/", 200, headers={"Accept-Encoding": "gzip"})
        acceptance.require(
            headers.get("Content-Encoding") == "gzip" and b"<html" in gzip.decompress(payload),
            "HTML compression missing",
        )
        connection = http.client.HTTPConnection("127.0.0.1", stack.http_port)
        connection.request("GET", "/?keep=1", headers={"Host": CUSTOMER})
        response = connection.getresponse()
        acceptance.require(
            response.status == 308
            and response.getheader("Location") == f"https://{CUSTOMER}/?keep=1",
            "HTTP redirect lost URI",
        )
        response.read()
        connection.close()
        init = {"init_data": acceptance.launch_data(stack.token, 900001)}
        data, headers = stack.request(
            "POST",
            "/api/v1/users/auth/telegram",
            200,
            body=init,
            headers={"Origin": stack.customer},
        )
        cookie = headers["Set-Cookie"]
        acceptance.require(
            all(flag in cookie for flag in ("Secure", "HttpOnly", "SameSite=strict")),
            "session cookie flags",
        )
        acceptance.require(headers.get("Cache-Control") == "no-store", "login cache policy")
        session = {"Cookie": cookie.split(";", 1)[0], "Origin": stack.customer}
        restored, headers = stack.request(
            "POST", "/api/v1/users/auth/session", 200, headers=session
        )
        acceptance.require(
            json.loads(restored)["user"]["id"] == json.loads(data)["user"]["id"]
            and headers.get("Cache-Control") == "no-store",
            "session restore identity/cache",
        )
        bearer = {
            "Authorization": "Bearer " + json.loads(restored)["access_token"],
            "X-MAI-Public-API": "0",
            "X-Forwarded-For": "127.0.0.1",
        }
        for method, path, body in (
            ("GET", "/api/v1/users/me", None),
            ("PATCH", "/api/v1/users/me", {"full_name": "Release Customer"}),
            ("GET", "/api/v1/orders/slots?limit=1", None),
            ("GET", "/api/v1/orders/?limit=1", None),
            ("GET", "/api/v1/orders/wallet", None),
        ):
            _, headers = stack.request(method, path, 200, body=body, headers=bearer)
            acceptance.require(
                headers.get("Cache-Control") == "no-store", "private response cached"
            )
        staff_bearer = {
            "Authorization": "Bearer " + self.tokens["ADMIN"],
            "X-MAI-Public-API": "0",
            "X-Forwarded-For": "127.0.0.1",
        }
        for path in (
            "/api/v1/users/me",
            "/api/v1/orders/",
            "/api/v1/orders/wallet",
            "/api/v1/orders/slots",
        ):
            stack.request("GET", path, 403, headers=staff_bearer)
        stack.request("GET", "/api/v1/users/me", 200, staff=True, headers=staff_bearer)
        stack.request("POST", "/api/v1/users/auth/logout", 204, headers=session)
        stack.request("POST", "/api/v1/users/auth/session", 401, headers=session)

    def webhook(self):
        stack = self.stack
        body = {
            "update_id": 702,
            "message": {
                "from": {"id": 900001},
                "chat": {"id": 900001, "type": "private"},
                "date": int(time.time()),
                "write_access_allowed": {},
            },
        }
        for path in (WEBHOOK + "/", WEBHOOK + "?ignored=1"):
            stack.request("POST", path, 404, body=body)
        stack.request("GET", WEBHOOK, 404)
        stack.request("POST", WEBHOOK, 404, staff=True, body=body)
        stack.request("POST", WEBHOOK, 403, body=body)
        stack.request(
            "POST", WEBHOOK, 403, body=body, headers={"X-Telegram-Bot-Api-Secret-Token": "invalid"}
        )
        for _ in range(2):
            stack.request(
                "POST",
                WEBHOOK,
                204,
                body=body,
                headers={"X-Telegram-Bot-Api-Secret-Token": stack.secret},
            )
        # Switch the real flag through Compose, then restore the same candidate configuration.
        original = stack.compose[:]
        flag = stack.directory / "disabled.json"
        flag.write_text(
            json.dumps({"services": {"edge": {"environment": {"PROD_WEBHOOK_ENABLED": "false"}}}})
        )
        stack.compose += ["-f", str(flag)]
        stack.recreate_edge()
        stack.request(
            "POST",
            WEBHOOK,
            404,
            body=body,
            headers={"X-Telegram-Bot-Api-Secret-Token": stack.secret},
        )
        stack.compose = original
        stack.recreate_edge()

    def rate_limit(self):
        stack = self.stack
        # Fresh limiter, independent of the successful fixture logins.
        stack.recreate_edge()
        for _ in range(10):
            stack.request(
                "POST",
                "/api/v1/users/auth/staff",
                401,
                staff=True,
                body={"username": "unknown", "password": "synthetic-password"},
            )
        stack.request(
            "POST",
            "/api/v1/users/auth/staff",
            429,
            staff=True,
            body={},
            headers={"X-Forwarded-For": "198.51.100.7"},
        )
        for _ in range(12):
            stack.request("GET", "/api/v1/users/me", 401, staff=True)
            stack.request(
                "POST", "/api/v1/users/auth/session", 401, headers={"Origin": stack.customer}
            )
        time.sleep(61)
        stack.request(
            "POST",
            "/api/v1/users/auth/staff",
            401,
            staff=True,
            body={"username": "unknown", "password": "synthetic-password"},
        )
        original = stack.compose[:]
        denied = stack.directory / "denied.json"
        denied.write_text(
            json.dumps(
                {"services": {"edge": {"environment": {"PROD_KITCHEN_CIDRS": "192.0.2.1/32"}}}}
            )
        )
        stack.compose += ["-f", str(denied)]
        stack.recreate_edge()
        stack.request(
            "POST",
            "/api/v1/users/auth/staff",
            403,
            staff=True,
            body={},
            headers={"X-Forwarded-For": "192.0.2.1", "Forwarded": "for=192.0.2.1"},
        )
        stack.compose = original
        stack.recreate_edge()

    def socket(self, token):
        stack = self.stack
        connection = LoopbackHTTPS(KITCHEN, stack.port, context=stack.context, timeout=20)
        connection.connect()
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        request = (
            f"GET /api/v1/ws/kitchen HTTP/1.1\r\nHost: {KITCHEN}\r\n"
            f"Origin: {stack.staff}\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n"
            f"Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\n\r\n"
        )
        connection.sock.sendall(request.encode())
        response = http.client.HTTPResponse(connection.sock)
        response.begin()
        acceptance.require(response.status == 101, "WSS upgrade failed")
        payload = json.dumps({"type": "auth", "access_token": token}).encode()
        mask = secrets.token_bytes(4)
        length = len(payload)
        header = (
            bytes([0x81, 0x80 | length])
            if length < 126
            else bytes([0x81, 0xFE]) + struct.pack("!H", length)
        )
        connection.sock.sendall(
            header + mask + bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
        )
        connection._ws_response = response
        return connection, response.fp

    @staticmethod
    def frame(stream):
        opcode, length = stream.read(2)
        length &= 127
        if length == 126:
            length = struct.unpack("!H", stream.read(2))[0]
        if length == 127:
            length = struct.unpack("!Q", stream.read(8))[0]
        acceptance.require(length < 65536, "oversized WebSocket frame")
        return opcode & 15, stream.read(length)

    def wss(self):
        for token, code in (("invalid", 4401), (self.tokens["CLIENT_A"], 4403)):
            connection, stream = self.socket(token)
            try:
                opcode, data = self.frame(stream)
                acceptance.require(
                    opcode == 8 and struct.unpack("!H", data[:2])[0] == code, "WSS auth rejection"
                )
            finally:
                connection.close()
        for _ in range(2):
            connection, stream = self.socket(self.tokens["COOK"])
            try:
                opcode, data = self.frame(stream)
                acceptance.require(
                    opcode == 1 and json.loads(data) == {"type": "ready"},
                    "authenticated WSS/reconnect",
                )
            finally:
                connection.close()

    def staff_flow(self):
        # Observe actual Kafka hints through WSS while the inherited journey prepares and issues.
        connection, stream = self.socket(self.tokens["COOK"])
        try:
            acceptance.require(json.loads(self.frame(stream)[1]) == {"type": "ready"}, "WSS ready")
            super().staff_flow()
            target = self.report["fixtures"]["completed_order"]
            for _ in range(20):
                opcode, data = self.frame(stream)
                hint = json.loads(data)
                if opcode == 1 and hint.get("order_id") == target:
                    break
            else:
                raise acceptance.CheckFailure("missing live order hint")
        finally:
            connection.close()

    def delivery(self):
        program = """
import asyncio, json
from sqlalchemy import select
from notification_service.config import Settings
from notification_service.infrastructure.models import ReadyDispatch, DeliveryAttempt
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
async def main():
    engine = create_async_engine(Settings().database_url.get_secret_value())
    async with async_sessionmaker(engine)() as db:
        states = list(await db.scalars(select(ReadyDispatch.state)))
        attempts = list(await db.scalars(select(DeliveryAttempt.outcome)))
        print(json.dumps([states, attempts]))
    await engine.dispose()
asyncio.run(main())
"""
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            observed = json.loads(self.stack.python("notification-service", program, {}))
            if observed == [["sent"], ["sent"]]:
                break
            time.sleep(2)
        acceptance.require(observed == [["sent"], ["sent"]], "READY delivery must commit once")
        count = self.stack.run("logs", "--no-log-prefix", "fake-bot")
        acceptance.require(
            count.count("synthetic_send_count=1") == 1 and "synthetic_send_count=2" not in count,
            "fake Telegram send count",
        )
        return {"ready_dispatches": 1, "attempts": 1, "synthetic_sends": 1}

    def upgrade(self):
        # Repeat the migration/start sequence over the same disposable volumes.
        self.stack.run(
            "stop",
            "edge",
            "outbox-worker",
            "notification-inbox",
            "notification-dispatch",
            "websocket-service",
            *acceptance.DATABASE_SERVICES,
            timeout=90,
        )
        for service in acceptance.DATABASE_SERVICES:
            self.stack.run(
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "/app/.venv/bin/alembic",
                service,
                "upgrade",
                "head",
                timeout=90,
            )
        self.stack.run("up", "-d", "--no-build", "--wait", "--wait-timeout", "180", timeout=210)
        self.wallet(acceptance.CREDIT - acceptance.NEW_PRICE)
        order, _ = self.http(
            "GET", "/api/v1/orders/" + self.report["fixtures"]["completed_order"], 200, "CLIENT_A"
        )
        acceptance.require(order["status"] == "COMPLETED", "upgrade lost order")
        self.delivery()

    def logs(self):
        marker = "release-sensitive-" + secrets.token_hex(12)
        self.stack.request(
            "GET",
            "/?token="
            + marker
            + "&access_token="
            + marker
            + "&initData="
            + marker
            + "&tgWebAppData="
            + marker,
            200,
            headers={
                "Authorization": "Bearer " + marker,
                "Cookie": "session=" + marker,
                "X-Telegram-Bot-Api-Secret-Token": marker,
            },
        )
        logs = self.stack.run("logs", "--no-log-prefix", "edge")
        acceptance.require(
            marker not in logs
            and self.stack.secret not in logs
            and self.stack.token not in logs
            and all(token not in logs for token in self.tokens.values()),
            "credential leaked to edge logs",
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    acceptance.require(
        not args.output.resolve().is_relative_to(ROOT), "evidence must be outside source"
    )
    report = {
        "source_revision": acceptance.command(["git", "rev-parse", "HEAD"]),
        "checks": [],
        "fixtures": {},
        "http_observations": [],
        "database_observations": [],
    }
    failed = False
    with TemporaryDirectory(prefix="mai-prod-test-") as directory:
        stack = Stack(Path(directory))
        journey = Journey(stack, report)
        stages = [
            ("isolated production model", stack.configure),
            ("pinned images and modules", stack.build),
            ("validated edge and fresh migrations", stack.start),
            ("baseline Nginx and Caddy compatibility", journey.proxy_compatibility),
            ("Mac static artifact rollback", journey.static_rollback),
            ("synthetic login", journey.login),
            ("TLS routes and customer session", journey.session_and_routes),
            ("webhook flag, secret and replay", journey.webhook),
            ("rolling staff login limit and network restriction", journey.rate_limit),
            ("authenticated WSS and reconnect", journey.wss),
            ("menu and slot administration", journey.seed),
            ("ADMIN wallet credit", journey.credit),
            ("duplicate debit, cancellation and refund", journey.duplicates_and_refund),
            ("repricing", journey.reprice),
            ("staff preparation, READY and issuance with WSS", journey.staff_flow),
            ("one fake READY delivery", journey.delivery),
            ("upgrade on same volumes", journey.upgrade),
            ("credential-free request logs", journey.logs),
        ]
        try:
            for name, check in stages:
                print(name, flush=True)
                observed = check()
                report["checks"].append({"stage": name, "status": "pass", "observed": observed})
        except Exception as error:
            failed = True
            report["checks"].append(
                {
                    "stage": name,
                    "status": "fail",
                    "reason": str(error)
                    if isinstance(error, acceptance.CheckFailure)
                    else type(error).__name__,
                }
            )
            # Never publish raw service logs, substituted config, credentials, or launch data.
            print(f"Failed stage: {name} ({type(error).__name__})", flush=True)
        finally:
            stack.run("down", "--volumes", "--remove-orphans", timeout=120)
            report["cleanup"] = "pass"
            report["passed"] = not failed
            args.output.write_text(json.dumps(report, indent=2) + "\n")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
