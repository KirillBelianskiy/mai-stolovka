from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from order_service.application.schemas import OrderCreate, SlotWrite
from order_service.application.service import fingerprint


@pytest.mark.parametrize("quantity", [0, -1, True, 1.5, "1"])
def test_quantity_is_strict_positive_integer(quantity: object) -> None:
    with pytest.raises(ValidationError):
        OrderCreate.model_validate(
            {
                "slot_id": str(uuid4()),
                "expected_total_amount": 1,
                "items": [{"menu_item_id": str(uuid4()), "quantity": quantity}],
            }
        )


def test_client_prices_and_duplicate_lines_are_rejected() -> None:
    line = {"menu_item_id": str(uuid4()), "quantity": 1}
    for body in [
        {"items": [line, line]},
        {"items": [line], "total_amount": 1},
        {"items": [{**line, "price_at_moment": 1}]},
    ]:
        with pytest.raises(ValidationError):
            OrderCreate.model_validate(
                {"slot_id": str(uuid4()), "expected_total_amount": 1, **body}
            )


def test_fingerprint_ignores_cart_order() -> None:
    lines = [{"menu_item_id": str(uuid4()), "quantity": 1} for _ in range(2)]
    body = {"slot_id": str(uuid4()), "expected_total_amount": 1, "items": lines}
    assert fingerprint(OrderCreate.model_validate(body)) == fingerprint(
        OrderCreate.model_validate({**body, "items": list(reversed(lines))})
    )


def test_slot_requires_timezone_and_ordered_times() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        SlotWrite.model_validate(
            {
                "start_time": now.replace(tzinfo=None).isoformat(),
                "end_time": (now + timedelta(minutes=10)).isoformat(),
                "capacity": 1,
            }
        )
    with pytest.raises(ValidationError):
        SlotWrite(start_time=now, end_time=now - timedelta(minutes=1), capacity=1)
