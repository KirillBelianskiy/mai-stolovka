import json
from datetime import datetime
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator

Status = Literal["PENDING", "PREPARING", "READY", "COMPLETED", "CANCELLED"]
EventType = Literal["ORDER_CREATED", "ORDER_STATUS_UPDATED", "ORDER_CANCELLED"]
OrderVersion = Annotated[int, Field(strict=True, ge=1, le=2**31 - 1)]
TRANSITIONS = {"PENDING": "PREPARING", "PREPARING": "READY", "READY": "COMPLETED"}


def parse_uuid(value: object) -> UUID:
    if not isinstance(value, str) or len(value) != 36:
        raise ValueError("Expected a UUID")
    parsed = UUID(value)
    if str(parsed) != value.lower():
        raise ValueError("Expected a UUID")
    return parsed


EventUUID = Annotated[UUID, BeforeValidator(parse_uuid)]


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_number: str = Field(min_length=1, max_length=32)
    user_id: EventUUID
    slot_id: EventUUID
    status: Status
    total_amount: int = Field(strict=True, ge=0, le=2**31 - 1)
    order_version: OrderVersion
    previous_status: Literal["PENDING", "PREPARING", "READY"] | None = None


class OrderEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: EventUUID
    aggregate_id: EventUUID
    event_type: EventType
    event_version: int = Field(strict=True, ge=1, le=1)
    occurred_at: datetime
    payload: Payload

    @field_validator("occurred_at", mode="before")
    @classmethod
    def require_utc_timestamp(cls, value: object) -> object:
        if not isinstance(value, str) or not value.endswith("Z"):
            raise ValueError("Expected a UTC date-time")
        return value

    @model_validator(mode="after")
    def validate_transition(self) -> Self:
        order = self.payload
        previous = order.previous_status
        if self.event_type == "ORDER_CREATED":
            valid = (
                order.status == "PENDING"
                and order.order_version == 1
                and "previous_status" not in order.model_fields_set
            )
        elif self.event_type == "ORDER_CANCELLED":
            valid = (
                previous in {"PENDING", "PREPARING"}
                and order.status == "CANCELLED"
                and order.order_version >= 2
            )
        else:
            valid = (
                previous is not None
                and TRANSITIONS[previous] == order.status
                and order.order_version >= 2
            )
        if not valid:
            raise ValueError("Invalid order event transition")
        return self


def unique_fields(fields: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in fields:
        if name in result:
            raise ValueError("Duplicate record field")
        result[name] = value
    return result


def order_hint(key: bytes | None, value: bytes | None) -> tuple[UUID, int]:
    if key is None or len(key) != 36 or value is None or len(value) > 65536:
        raise ValueError("Invalid record size")
    event = OrderEvent.model_validate(
        json.loads(value.decode("utf-8"), object_pairs_hook=unique_fields)
    )
    if parse_uuid(key.decode("ascii")) != event.aggregate_id:
        raise ValueError("Record key does not match the order")
    return event.aggregate_id, event.payload.order_version
