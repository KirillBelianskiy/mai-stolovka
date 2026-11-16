import asyncio
import base64
import json
import os
import sys
from contextlib import suppress
from datetime import UTC, datetime
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from test_dispatch_integration import evidence, ready
from test_inbox_integration import record, run_test

pytestmark = pytest.mark.integration


def test_standalone_worker_sends_to_fake_and_excludes_second_process(capfd):
    async def check(inbox):
        body = ready()
        await inbox.ingest(record(body))
        user_id = UUID(body["payload"]["user_id"])
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        requests = []

        async def fake_user(method, path, headers, payload):
            assert method == "GET" and path == f"/internal/v1/notification-recipients/{user_id}"
            claims = jwt.decode(
                headers["authorization"].removeprefix("Bearer "),
                key.public_key(),
                algorithms=["RS256"],
                audience="mai-food-user",
                issuer="mai-food-notification",
            )
            assert claims["scope"] == "notification:recipient:read"
            return {
                "user_id": str(user_id),
                "state": "allowed",
                "telegram_chat_id": 1234,
                "revision": 7,
                "observed_at": datetime.now(UTC).isoformat(),
                "evidence_kind": "write_access_allowed",
            }

        async def fake_bot(method, path, headers, payload):
            assert method == "POST" and path == "/bot0:fake-test-token/sendMessage"
            assert "authorization" not in headers
            requests.append(payload)
            return {
                "ok": True,
                "result": {"message_id": 17, "chat": {"id": 1234, "type": "private"}},
            }

        async def start_server(handler):
            async def handle(reader, writer):
                try:
                    method, path, _ = (await reader.readline()).decode().strip().split()
                    headers = {}
                    while (line := await reader.readline()) != b"\r\n":
                        name, value = line.decode().split(":", 1)
                        headers[name.lower()] = value.strip()
                    length = int(headers.get("content-length", "0"))
                    payload = json.loads(await reader.readexactly(length)) if length else None
                    response = json.dumps(await handler(method, path, headers, payload)).encode()
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nConnection: close\r\n"
                        + f"Content-Length: {len(response)}\r\n\r\n".encode()
                        + response
                    )
                    await writer.drain()
                finally:
                    writer.close()
                    await writer.wait_closed()

            return await asyncio.start_server(handle, "127.0.0.1", 0)

        async with await start_server(fake_user) as user, await start_server(fake_bot) as bot:
            env = {
                **os.environ,
                "APP_DATABASE_URL": os.environ["MAI_TEST_DATABASE_URL"],
                "APP_DISPATCH_USER_URL": f"http://127.0.0.1:{user.sockets[0].getsockname()[1]}",
                "APP_DISPATCH_FAKE_BOT_URL": f"http://127.0.0.1:{bot.sockets[0].getsockname()[1]}",
                "APP_DISPATCH_BOT_MODE": "fake",
                "APP_DISPATCH_SIGNING_KEY_BASE64": base64.b64encode(pem).decode(),
            }
            env.pop("APP_DISPATCH_BOT_TOKEN", None)
            command = (sys.executable, "-m", "notification_service.dispatch")
            disabled = await asyncio.create_subprocess_exec(
                *command, env={**env, "APP_DISPATCH_BOT_MODE": "disabled"}
            )
            assert await asyncio.wait_for(disabled.wait(), 10) == 0
            assert not requests and (await evidence(inbox))[0] is None

            probe = await asyncio.create_subprocess_exec(*command, "--check", env=env)
            assert await asyncio.wait_for(probe.wait(), 10) == 0
            assert not requests and (await evidence(inbox))[0] is None

            worker = await asyncio.create_subprocess_exec(*command, env=env)
            try:
                async with asyncio.timeout(10):
                    while True:
                        row, attempts = await evidence(inbox)
                        if row and row.state == "sent":
                            break
                        await asyncio.sleep(0.05)
                second = await asyncio.create_subprocess_exec(*command, env=env)
                assert await asyncio.wait_for(second.wait(), 10) == 1
                assert attempts[0].message_id == 17 and len(requests) == 1
                assert requests[0]["text"] == "Заказ MAI-000001 готов к выдаче."
            finally:
                if worker.returncode is None:
                    with suppress(ProcessLookupError):
                        worker.terminate()
                assert await asyncio.wait_for(worker.wait(), 10) == 0

    run_test(check)
    output = capfd.readouterr()
    assert "fake-test-token" not in output.err
    assert "Authorization" not in output.err
