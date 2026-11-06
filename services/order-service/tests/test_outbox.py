import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from order_service.application.outbox import (
    AmbiguousPublication,
    InvalidEvent,
    PendingEvent,
    Relay,
)
from order_service.config import Settings


def event() -> PendingEvent:
    now = datetime.now(UTC)
    order_id, event_id = uuid4(), uuid4()
    envelope = {
        "event_id": str(event_id),
        "event_type": "ORDER_CREATED",
        "event_version": 1,
        "occurred_at": now.isoformat().replace("+00:00", "Z"),
        "aggregate_id": str(order_id),
        "payload": {
            "order_number": "MAI-000001",
            "user_id": str(uuid4()),
            "slot_id": str(uuid4()),
            "status": "PENDING",
            "total_amount": 12000,
            "order_version": 1,
        },
    }
    return PendingEvent(event_id, order_id, 1, "ORDER_CREATED", now, envelope)


class Store:
    def __init__(self, row: PendingEvent) -> None:
        self.row = row
        self.marked = False
        self.guard_lost = False
        self.mark_error = False

    async def check_guard(self) -> None:
        if self.guard_lost:
            raise RuntimeError("guard lost")

    async def next_event(self) -> PendingEvent | None:
        return None if self.marked else self.row

    async def mark_published(self, row: PendingEvent) -> None:
        if self.mark_error:
            raise RuntimeError("crash after ACK")
        self.marked = True


class Publisher:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.sent: list[tuple[bytes, bytes]] = []
        self.delay = 0.0
        self.lose_guard = False

    async def publish(self, key: bytes, value: bytes) -> None:
        assert not self.store.marked
        self.sent.append((key, value))
        await asyncio.sleep(self.delay)
        if self.lose_guard:
            self.store.guard_lost = True


def test_ack_before_mark_and_no_routine_republish() -> None:
    async def run() -> None:
        row = event()
        store = Store(row)
        publisher = Publisher(store)
        relay = Relay(store, publisher, Settings())
        assert await relay.publish_next()
        assert store.marked and len(publisher.sent) == 1
        assert publisher.sent[0][0] == str(row.aggregate_id).encode()
        assert json.loads(publisher.sent[0][1]) == row.envelope
        assert not await relay.publish_next()
        assert len(publisher.sent) == 1

    asyncio.run(run())


def test_crash_after_ack_replays_original_event() -> None:
    async def run() -> None:
        row = event()
        store = Store(row)
        publisher = Publisher(store)
        relay = Relay(store, publisher, Settings())
        store.mark_error = True
        with pytest.raises(RuntimeError, match="crash after ACK"):
            await relay.publish_next()
        assert not store.marked
        store.mark_error = False
        await relay.publish_next()
        assert publisher.sent[0] == publisher.sent[1]

    asyncio.run(run())


@pytest.mark.parametrize(
    "field", ["event_id", "aggregate_id", "event_type", "occurred_at", "payload"]
)
def test_invalid_or_mismatched_event_is_retained(field: str) -> None:
    async def run() -> None:
        row = event()
        original = deepcopy(row.envelope)
        if field == "payload":
            row.envelope["payload"]["order_version"] = 2
        elif field == "event_type":
            row.envelope[field] = "UNKNOWN"
        elif field == "occurred_at":
            row.envelope[field] = "2020-01-01T00:00:00Z"
        else:
            row.envelope[field] = str(uuid4())
        store = Store(row)
        publisher = Publisher(store)
        with pytest.raises(InvalidEvent):
            await Relay(store, publisher, Settings()).publish_next()
        assert not store.marked and publisher.sent == []
        assert row.envelope != original

    asyncio.run(run())


def test_send_deadline_never_marks_or_sends_next() -> None:
    async def run() -> None:
        store = Store(event())
        publisher = Publisher(store)
        publisher.delay = 10
        relay = Relay(store, publisher, Settings(outbox_send_timeout_seconds=0.01))
        with pytest.raises(AmbiguousPublication):
            await relay.publish_next()
        assert not store.marked and len(publisher.sent) == 1

    asyncio.run(run())


def test_guard_loss_after_ack_prevents_mark() -> None:
    async def run() -> None:
        store = Store(event())
        publisher = Publisher(store)
        publisher.lose_guard = True
        with pytest.raises(RuntimeError, match="guard lost"):
            await Relay(store, publisher, Settings()).publish_next()
        assert not store.marked

    asyncio.run(run())


def test_runtime_schema_matches_canonical_contract() -> None:
    root = Path(__file__).resolve().parents[3]
    canonical = root / "packages/contracts/events/envelope-v1.schema.json"
    bundled = Path(__file__).resolve().parents[1] / "src/order_service/resources/events-v1.json"
    assert bundled.read_bytes() == canonical.read_bytes()
