from typing import Annotated
from uuid import UUID

import httpx
from fastapi import HTTPException
from pydantic import Field, TypeAdapter, ValidationError

Quantity = Annotated[int, Field(strict=True, ge=0, le=2**31 - 1)]
stock_counts = TypeAdapter(dict[UUID, Quantity])


class StockClient:
    def __init__(self, base_url: str | None) -> None:
        self.client = (
            httpx.AsyncClient(base_url=base_url, timeout=2.0, trust_env=False) if base_url else None
        )

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()

    async def remaining(self, ids: list[UUID]) -> dict[UUID, int]:
        if not ids or self.client is None:
            return {}
        try:
            response = await self.client.post(
                "/internal/menu-stock", json={"item_ids": [str(item_id) for item_id in ids]}
            )
            response.raise_for_status()
            counts = stock_counts.validate_json(response.content)
            if not counts.keys() <= set(ids):
                raise ValueError("Unexpected dish in stock response")
            return counts
        except (httpx.HTTPError, ValidationError, ValueError):
            raise HTTPException(503, "Dish stock is temporarily unavailable") from None
