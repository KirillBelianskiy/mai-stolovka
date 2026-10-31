import asyncio
from typing import Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, Field

from order_service.config import Settings
from order_service.domain.orders import DishSnapshot, OrderError


class SnapshotItem(BaseModel):
    id: UUID
    name: str = Field(min_length=1, max_length=256)
    price: int = Field(strict=True, ge=0, le=2**31 - 1)
    is_available: Literal[True]


class SnapshotResponse(BaseModel):
    items: list[SnapshotItem] = Field(min_length=1, max_length=100)


class MenuClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings
        self.client = client or httpx.AsyncClient(
            base_url=settings.menu_base_url,
            timeout=settings.menu_timeout_seconds,
            trust_env=False,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def snapshot(self, item_ids: list[UUID]) -> list[DishSnapshot]:
        try:
            async with asyncio.timeout(self.settings.menu_timeout_seconds):
                response = await self.client.post(
                    "/item-snapshots", json={"item_ids": [str(i) for i in item_ids]}
                )
                if response.status_code == 409:
                    raise OrderError(409, "ITEM_UNAVAILABLE", "One or more dishes are unavailable")
                response.raise_for_status()
                body = SnapshotResponse.model_validate(response.json())
                ids = [item.id for item in body.items]
                if len(set(ids)) != len(ids) or set(ids) != set(item_ids):
                    raise ValueError("Menu snapshot does not match the requested dishes")
                return [DishSnapshot(item.id, item.name, item.price) for item in body.items]
        except (httpx.HTTPError, ValueError, TimeoutError):
            raise OrderError(
                503, "MENU_UNAVAILABLE", "Menu service is unavailable; retry safely"
            ) from None

    async def close(self) -> None:
        await self.client.aclose()
