import asyncio
import json
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
    except (RuntimeError, WebSocketDisconnect):
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
        auth_frame = await asyncio.wait_for(
            websocket.receive_text(), timeout=settings.websocket_auth_timeout_seconds
        )
    except TimeoutError:
        await websocket.close(code=4401)
        return
    except WebSocketDisconnect:
        return

    if len(auth_frame.encode("utf-8")) > settings.websocket_max_frame_bytes:
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
    except RuntimeError:
        await websocket.close(code=1013)
        return
    except (ValueError, TypeError, jwt.InvalidTokenError, ValidationError):
        await websocket.close(code=4401)
        return

    if claims.role not in {"COOK", "CASHIER", "ADMIN"}:
        await websocket.close(code=4403)
        return

    hub: KitchenHub = websocket.app.state.hub
    try:
        client_id, client = hub.connect()
    except RuntimeError:
        await websocket.close(code=1013)
        return
    sender = asyncio.create_task(_send_messages(websocket, client.messages))
    try:
        while True:
            remaining = claims.exp - datetime.now(UTC).timestamp()
            if remaining <= 0:
                await websocket.close(code=4401)
                return
            receiver = asyncio.create_task(websocket.receive_text())
            overflow = asyncio.create_task(client.overflow.wait())
            shutdown = asyncio.create_task(client.shutdown.wait())
            try:
                done, _ = await asyncio.wait(
                    {receiver, overflow, shutdown, sender},
                    timeout=remaining,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                for task in (receiver, overflow, shutdown):
                    if not task.done():
                        task.cancel()
            if not done:
                await websocket.close(code=4401)
                return
            if overflow in done and overflow.result():
                await websocket.close(code=1013)
                return
            if sender in done:
                return
            if shutdown in done and shutdown.result():
                await websocket.close(code=1012)
                return
            try:
                frame = receiver.result()
            except WebSocketDisconnect:
                return
            if len(frame.encode("utf-8")) > settings.websocket_max_frame_bytes:
                await websocket.close(code=1008)
                return
            await websocket.close(code=1008)
            return
    finally:
        hub.disconnect(client_id)
        sender.cancel()
        try:
            await sender
        except asyncio.CancelledError:
            pass
