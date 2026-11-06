import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiokafka import TopicPartition

from notification_service.config import Settings
from notification_service.infrastructure.inbox import RecoveryRequired
from notification_service.ingest import Assignments, consume, process_record


def test_durable_write_precedes_exact_next_offset_commit():
    async def run():
        steps = []
        store, consumer = AsyncMock(), AsyncMock()
        consumer.assignment = lambda: {TopicPartition("orders", 0)}

        async def own(record):
            steps.append("db_commit")
            return "ACCEPTED"

        async def commit(offsets):
            steps.append(("kafka_commit", offsets))

        store.ingest.side_effect, consumer.commit.side_effect = own, commit
        message = SimpleNamespace(topic="orders", partition=0, offset=7, key=b"k", value=b"v")
        assert await process_record(store, consumer, message) == "ACCEPTED"
        assert steps == ["db_commit", ("kafka_commit", {TopicPartition("orders", 0): 8})]

    asyncio.run(run())


def test_poll_waits_for_verified_assignment_and_failed_prefix_stops_batch():
    async def run():
        store, consumer = AsyncMock(), AsyncMock()
        settings, stop = Settings(), asyncio.Event()
        assignments = Assignments(store, consumer, settings)
        task = asyncio.create_task(consume(store, consumer, assignments, settings, stop))
        await asyncio.sleep(0)
        consumer.getmany.assert_not_awaited()
        tp = TopicPartition("orders", 0)
        consumer.assignment = lambda: {tp}
        consumer.getmany.return_value = {
            tp: [
                SimpleNamespace(topic="orders", partition=0, offset=i, key=None, value=b"bad")
                for i in range(2)
            ]
        }
        assignments.active.add(tp)
        store.ingest.side_effect = RuntimeError("failure before durable commit")
        assignments.ready.set()
        with pytest.raises(RuntimeError):
            await task
        assert store.ingest.await_count == 1
        consumer.commit.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("stage", ["database", "guard", "assignment"])
def test_failure_never_commits_ahead(stage):
    async def run():
        store, consumer = AsyncMock(), AsyncMock()
        consumer.assignment = lambda: (
            set() if stage == "assignment" else {TopicPartition("orders", 0)}
        )
        if stage == "database":
            store.ingest.side_effect = RuntimeError("private connection")
        if stage == "guard":
            store.check_guard.side_effect = [None, RecoveryRequired("guard_lost")]
        with pytest.raises((RuntimeError, RecoveryRequired)):
            await process_record(
                store,
                consumer,
                SimpleNamespace(topic="orders", partition=0, offset=0, key=None, value=b"bad"),
            )
        consumer.commit.assert_not_awaited()

    asyncio.run(run())
