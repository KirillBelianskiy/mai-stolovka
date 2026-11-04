import hashlib
import json
from dataclasses import dataclass
from importlib.resources import files
from typing import Any
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]

MAX_RECORD_BYTES = 65536


class InvalidRecord(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


@dataclass(frozen=True)
class Event:
    event_id: UUID
    order_id: UUID
    user_id: UUID
    version: int
    status: str
    previous_status: str | None
    content_hash: str
    state_hash: str
    identity_hash: str
    envelope: dict[str, Any]


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidRecord("duplicate_key")
        result[key] = value
    return result


def invalid_constant(value: str) -> None:
    raise InvalidRecord("invalid_number")


SCHEMA = json.loads(files("notification_service").joinpath("resources/events-v1.json").read_text())
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def parse_event(key: bytes | None, value: bytes | None) -> Event:
    if value is None or len(value) > MAX_RECORD_BYTES:
        raise InvalidRecord("record_size")
    try:
        body = json.loads(
            value.decode("utf-8"), object_pairs_hook=unique_object, parse_constant=invalid_constant
        )
        if next(VALIDATOR.iter_errors(body), None) is not None:
            raise InvalidRecord("schema")
        if key is None or len(key) != 36 or UUID(key.decode("ascii")) != UUID(body["aggregate_id"]):
            raise InvalidRecord("key_mismatch")
        payload = body["payload"]
        return Event(
            UUID(body["event_id"]),
            UUID(body["aggregate_id"]),
            UUID(payload["user_id"]),
            payload["order_version"],
            payload["status"],
            payload.get("previous_status"),
            digest(body),
            digest({"event_type": body["event_type"], "payload": payload}),
            digest(
                {
                    name: payload[name]
                    for name in ("order_number", "user_id", "slot_id", "total_amount")
                }
            ),
            body,
        )
    except InvalidRecord:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        raise InvalidRecord("malformed") from None


def compatible(first: Event, second: Event) -> bool:
    low, high = sorted((first, second), key=lambda item: item.version)
    if low.version == high.version:
        return low.state_hash == high.state_hash
    if low.status in {"COMPLETED", "CANCELLED"}:
        return False
    distance = high.version - low.version
    if high.status == "CANCELLED":
        if low.status not in {"PENDING", "PREPARING"}:
            return False
        needed = 2 if low.status == "PENDING" and high.previous_status == "PREPARING" else 1
    else:
        ranks = {"PENDING": 0, "PREPARING": 1, "READY": 2, "COMPLETED": 3}
        needed = ranks[high.status] - ranks[low.status]
        if needed <= 0:
            return False
    return distance >= needed and (distance != 1 or high.previous_status == low.status)
