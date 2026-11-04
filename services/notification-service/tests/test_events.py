import json
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import pytest

from notification_service.domain.events import InvalidRecord, compatible, parse_event


def test_bundled_schema_matches_unchanged_canonical_contract():
    canonical = (
        Path(__file__).resolve().parents[3] / "packages/contracts/events/envelope-v1.schema.json"
    )
    assert (
        files("notification_service").joinpath("resources/events-v1.json").read_bytes()
        == canonical.read_bytes()
    )


def event(status="READY", version=3):
    previous = {
        "PREPARING": "PENDING",
        "READY": "PREPARING",
        "COMPLETED": "READY",
        "CANCELLED": "PENDING",
    }
    body = {
        "event_id": str(uuid4()),
        "event_type": "ORDER_STATUS_UPDATED",
        "event_version": 1,
        "occurred_at": "2026-11-04T07:00:00Z",
        "aggregate_id": str(uuid4()),
        "payload": {
            "order_number": "MAI-000001",
            "user_id": str(uuid4()),
            "slot_id": str(uuid4()),
            "status": status,
            "total_amount": 12000,
            "order_version": version,
        },
    }
    if status == "PENDING":
        body["event_type"] = "ORDER_CREATED"
    else:
        body["payload"]["previous_status"] = previous[status]
    if status == "CANCELLED":
        body["event_type"] = "ORDER_CANCELLED"
    return body


def parsed(body):
    return parse_event(body["aggregate_id"].encode(), json.dumps(body).encode())


def test_key_order_does_not_change_canonical_hash():
    body = event()
    left = parsed(body)
    right = parse_event(body["aggregate_id"].encode(), json.dumps(body, sort_keys=True).encode())
    assert left.content_hash == right.content_hash
    changed = deepcopy(body)
    changed["event_id"] = str(uuid4())
    changed["occurred_at"] = "2026-11-04T07:01:00Z"
    assert parsed(changed).state_hash == left.state_hash
    assert parsed(changed).content_hash != left.content_hash


@pytest.mark.parametrize(
    "raw", [b"{", b"\xff", b'{"event_id":"a","event_id":"b"}', b'{"value":NaN}', b"x" * 65537]
)
def test_malformed_duplicate_keys_and_oversize_are_rejected(raw):
    with pytest.raises(InvalidRecord):
        parse_event(b"key", raw)


def test_schema_and_key_mismatch_are_rejected():
    body = event()
    with pytest.raises(InvalidRecord):
        parse_event(str(uuid4()).encode(), json.dumps(body).encode())
    body["payload"]["total_amount"] = True
    with pytest.raises(InvalidRecord):
        parsed(body)


def test_known_lifecycle_forks_and_impossible_adjacency_are_rejected():
    pending, ready, completed, cancelled = (
        parsed(event("PENDING", 1)),
        parsed(event()),
        parsed(event("COMPLETED", 4)),
        parsed(event("CANCELLED", 2)),
    )
    assert compatible(pending, ready) and compatible(ready, completed)
    assert not compatible(ready, cancelled)
    assert not compatible(cancelled, completed)
    assert not compatible(pending, parsed(event("READY", 2)))
    assert not compatible(ready, parsed(event("READY", 4)))
