import asyncio
import json
from contextlib import suppress
from datetime import UTC, datetime

import jwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from websocket_service.application.hub import KitchenHub
from websocket_service.config import Settings

router = APIRouter()


async def _send_messages(
    websocket: WebSocket, client_queue: asyncio.Queue[dict[str, object]]
) -> None:
    try:
        while True:
            await websocket.send_json(await client_queue.get())
    except (OSError, RuntimeError, WebSocketDisconnect):
        return


@router.websocket("/api/v1/ws/kitchen")
async def kitchen_websocket(websocket: WebSocket) -> None:
    settings: Settings = websocket.app.state.settings
    origin = websocket.headers.get("origin")
    if origin is None or origin not in settings.origin_allowlist:
        await websocket.close(code=4403)
        return

    await websocket.accept()
    try:
        frame = await asyncio.wait_for(
            websocket.receive(), timeout=settings.websocket_auth_timeout_seconds
        )
    except TimeoutError:
        await websocket.close(code=4401)
        return
    if frame["type"] == "websocket.disconnect":
        return
    auth_frame = frame.get("text")
    if (
        not isinstance(auth_frame, str)
        or len(auth_frame.encode()) > settings.websocket_max_frame_bytes
    ):
        await websocket.close(code=1008)
        return
    try:
        message = json.loads(auth_frame)
        if not isinstance(message, dict) or message.get("type") != "auth":
            raise ValueError("Expected auth frame")
        token = message.get("access_token")
        if not isinstance(token, str):
            raise ValueError("Missing access token")
        claims = websocket.app.state.token_verifier.verify(token)
    except RecursionError:
        await websocket.close(code=4401)
        return
    except RuntimeError:
        await websocket.close(code=1013)
        return
    except (ValueError, TypeError, jwt.InvalidTokenError, ValidationError):
        await websocket.close(code=4401)
        return

    if claims.role not in {"COOK", "CASHIER", "ADMIN"}:
        await websocket.close(code=4403)
        return
    remaining = claims.exp - datetime.now(UTC).timestamp()
    if remaining <= 0:
        await websocket.close(code=4401)
        return

    hub: KitchenHub = websocket.app.state.hub
    try:
        client_id, client = hub.connect()
    except RuntimeError:
        await websocket.close(code=1013)
        return

    sender = asyncio.create_task(_send_messages(websocket, client.messages))
    receiver = asyncio.create_task(websocket.receive())
    overflow = asyncio.create_task(client.overflow.wait())
    unavailable = asyncio.create_task(client.unavailable.wait())
    shutdown = asyncio.create_task(client.shutdown.wait())
    tasks = (sender, receiver, overflow, unavailable, shutdown)
    try:
        done, _ = await asyncio.wait(tasks, timeout=remaining, return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        return
    finally:
        hub.disconnect(client_id)
        for task in tasks:
            task.cancel()
        with suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks, return_exceptions=True)

    if not done:
        await websocket.close(code=4401)
    elif shutdown in done:
        await websocket.close(code=1012)
    elif overflow in done or unavailable in done:
        await websocket.close(code=1013)
    elif receiver.done() and not receiver.cancelled():
        if receiver.result()["type"] != "websocket.disconnect":
            await websocket.close(code=1008)
