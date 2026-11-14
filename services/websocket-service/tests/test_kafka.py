import asyncio
import json
import os
from dataclasses import dataclass
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient, NewTopic

from websocket_service.application.hub import KitchenHub
from websocket_service.config import Settings
from websocket_service.domain.events import order_hint
from websocket_service.infrastructure.kafka import (
    Assignments,
    RecoveryRequired,
    consume,
    run_consumer,
    stop_consumer,
)

TOPIC = "orders.events.v1"
PARTITION = TopicPartition(TOPIC, 0)


def created(order_id: UUID) -> dict:
    return {
        "event_id": str(uuid4()),
        "aggregate_id": str(order_id),
        "event_type": "ORDER_CREATED",
        "event_version": 1,
        "occurred_at": "2026-11-14T10:00:00Z",
        "payload": {
            "order_number": "MAI-123",
            "user_id": str(uuid4()),
            "slot_id": str(uuid4()),
            "status": "PENDING",
            "total_amount": 100,
            "order_version": 1,
        },
    }


@pytest.mark.parametrize(
    "change", ["envelope", "version", "order_version", "status", "key", "duplicate_field"]
)
def test_rejects_invalid_v1_events(change: str) -> None:
    order_id = uuid4()
    event = created(order_id)
    key = str(order_id).encode()
    if change == "envelope":
        event["extra"] = "unexpected"
    elif change == "version":
        event["event_version"] = True
    elif change == "order_version":
        event["payload"]["order_version"] = 2
    elif change == "status":
        event["payload"]["status"] = "READY"
    elif change == "key":
        key = str(uuid4()).encode()
    body = json.dumps(event).encode()
    if change == "duplicate_field":
        body = b'{"event_version":2,' + body[1:]
    with pytest.raises(ValueError):
        order_hint(key, body)


@dataclass
class FakeConsumer:
    offset: int | None
    position: int | None = None

    def partitions_for_topic(self, topic: str) -> set[int]:
        return {0}

    async def beginning_offsets(self, partitions: set[TopicPartition]) -> dict:
        return {PARTITION: 3}

    async def end_offsets(self, partitions: set[TopicPartition]) -> dict:
        return {PARTITION: 8}

    async def committed(self, partition: TopicPartition) -> int | None:
        return self.offset

    def seek(self, partition: TopicPartition, offset: int) -> None:
        self.position = offset


@pytest.mark.parametrize(("offset", "expected"), [(None, 8), (5, 5), (8, 8), (2, None), (9, None)])
def test_assignment_position(offset: int | None, expected: int | None) -> None:
    async def scenario() -> None:
        hub = KitchenHub(2, ready=False)
        consumer = FakeConsumer(offset)
        assignment = Assignments(consumer, hub, TOPIC)
        await assignment.on_partitions_assigned({PARTITION})
        assert consumer.position == expected
        assert hub.ready == (expected is not None)
        assert isinstance(assignment.error, RecoveryRequired) == (expected is None)
        if hub.ready:
            _, client = hub.connect()
            await assignment.on_partitions_revoked({PARTITION})
            assert not hub.ready
            assert client.unavailable.is_set()

    asyncio.run(scenario())


def test_partial_assignment_cannot_admit_clients() -> None:
    hub = KitchenHub(2, ready=False)
    assignment = Assignments(FakeConsumer(4), hub, TOPIC)
    asyncio.run(assignment.on_partitions_assigned(set()))
    assert not hub.ready


def test_poison_record_never_commits_past_the_valid_prefix() -> None:
    async def scenario() -> None:
        order_id = uuid4()
        key = str(order_id).encode()
        value = json.dumps(created(order_id)).encode()
        commits = []
        hub = KitchenHub(4, ready=False)

        class BatchConsumer(FakeConsumer):
            async def getmany(self, *, timeout_ms: int, max_records: int) -> dict:
                return {
                    PARTITION: [
                        SimpleNamespace(key=key, value=body, offset=offset)
                        for offset, body in enumerate((value, b"invalid", value), start=3)
                    ],
                }

            async def commit(self, offsets: dict) -> None:
                assert client.messages.qsize() == 2
                commits.append(offsets[PARTITION])

        consumer = BatchConsumer(3)
        assignment = Assignments(consumer, hub, TOPIC)
        await assignment.on_partitions_assigned({PARTITION})
        _, client = hub.connect()
        with pytest.raises(RecoveryRequired, match="offset=4"):
            await consume(consumer, assignment, hub)
        assert commits == [4]

    asyncio.run(scenario())


@pytest.mark.skipif(not os.getenv("KITCHEN_TEST_KAFKA"), reason="Requires a disposable broker")
def test_real_kafka_restart_and_independent_groups() -> None:
    async def scenario() -> None:
        bootstrap = os.environ["KITCHEN_TEST_KAFKA"]
        suffix = uuid4().hex
        topic = f"kitchen-test-{suffix}"
        tp = TopicPartition(topic, 0)
        settings = Settings(
            kafka_bootstrap_servers=bootstrap,
            kitchen_kafka_topic=topic,
            kitchen_kafka_group=f"kitchen-test-{suffix}",
        )
        admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap)
        producer = AIOKafkaProducer(bootstrap_servers=bootstrap)
        notification = AIOKafkaConsumer(
            topic,
            bootstrap_servers=bootstrap,
            group_id=f"notification-test-{suffix}",
            auto_offset_reset="earliest",
            enable_auto_commit=False,
        )

        async def produce() -> str:
            order_id = uuid4()
            await producer.send_and_wait(
                topic, json.dumps(created(order_id)).encode(), key=str(order_id).encode()
            )
            return str(order_id)

        async def start_kitchen() -> tuple:
            worker = asyncio.create_task(run_consumer(settings, hub))
            workers.append(worker)
            while not hub.ready:
                assert not worker.done(), worker.exception()
                await asyncio.sleep(0.05)
            client_id, client = hub.connect()
            assert await client.messages.get() == {"type": "ready"}
            return worker, client_id, client

        hub = KitchenHub(4, ready=False)
        workers = []
        probe = AIOKafkaConsumer(bootstrap_servers=bootstrap, group_id=settings.kitchen_kafka_group)
        try:
            async with asyncio.timeout(50):
                await admin.start()
                await admin.create_topics([NewTopic(topic, 1, 1)])
                await producer.start()
                await probe.start()
                historical = await produce()
                worker, client_id, client = await start_kitchen()
                await notification.start()

                live = await produce()
                assert (await client.messages.get())["order_id"] == live
                assert (await notification.getone()).key.decode() == historical
                assert (await notification.getone()).key.decode() == live
                while await probe.committed(tp) != 2:
                    await asyncio.sleep(0.05)

                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
                assert client.unavailable.is_set()
                hub.disconnect(client_id)
                while_offline = await produce()

                _, _, replacement = await start_kitchen()
                assert (await replacement.messages.get())["order_id"] == while_offline
                assert (await notification.getone()).key.decode() == while_offline
        finally:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            await notification.stop()
            await probe.stop()
            await producer.stop()
            try:
                await admin.delete_topics([topic])
            finally:
                await admin.close()

    asyncio.run(scenario())


def test_cancelled_kafka_fetch_cannot_kill_the_reconnecting_worker() -> None:
    async def scenario() -> None:
        closed = False

        async def cancel_pending_fetch() -> None:
            raise asyncio.CancelledError

        async def close_broker_connection() -> None:
            nonlocal closed
            closed = True

        consumer = SimpleNamespace(
            stop=cancel_pending_fetch,
            _client=SimpleNamespace(close=close_broker_connection),
        )
        await stop_consumer(consumer)
        assert closed

    asyncio.run(scenario())
