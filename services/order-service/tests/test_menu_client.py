import asyncio
from uuid import uuid4

import httpx
import pytest

from order_service.config import Settings
from order_service.domain.orders import OrderError
from order_service.infrastructure.menu import MenuClient


def test_menu_snapshot_validates_response() -> None:
    item_id = uuid4()

    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="http://menu",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200,
                    json={
                        "items": [
                            {"id": str(item_id), "name": "Soup", "price": 100, "is_available": True}
                        ]
                    },
                )
            ),
        ) as http:
            items = await MenuClient(Settings(), http).snapshot([item_id])
            assert items[0].price == 100

    asyncio.run(run())


@pytest.mark.parametrize(
    "status,body",
    [
        (500, {}),
        (409, {}),
        (200, {"items": []}),
        (200, {"items": [{"id": str(uuid4()), "name": "Soup", "price": -1, "is_available": True}]}),
    ],
)
def test_bad_menu_response_fails_closed(status: int, body: object) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            base_url="http://menu",
            transport=httpx.MockTransport(lambda _: httpx.Response(status, json=body)),
        ) as http:
            with pytest.raises(OrderError) as error:
                await MenuClient(Settings(), http).snapshot([uuid4()])
            assert error.value.status == (409 if status == 409 else 503)

    asyncio.run(run())
