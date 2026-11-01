import asyncio
import json
import os
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaConsumer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from sqlalchemy import func, select, text
from test_outbox import event

from order_service.application.outbox import Relay
from order_service.domain.orders import OrderStatus
from order_service.infrastructure.kafka import KafkaPublisher
from order_service.infrastructure.models import Order, OutboxEvent, TimeSlot
from order_service.infrastructure.outbox import AlreadyRunning, GuardLost, PostgresOutbox
from order_service.outbox import serve

pytestmark = pytest.mark.integration


def store_for(settings) -> PostgresOutbox:
    return PostgresOutbox(settings.database_url.get_secret_value(), 1)


async def seed(store: PostgresOutbox, versions: int = 2, rollback: bool = False) -> list:
    first = event()
    rows = []
    async with store.database.sessions() as db:
        async with db.begin():
            slot = TimeSlot(
                id=first.envelope["payload"]["slot_id"],
                start_time=first.occurred_at + timedelta(hours=1),
                end_time=first.occurred_at + timedelta(hours=2),
                capacity=10,
                current_orders=1,
            )
            db.add(slot)
            await db.flush()
            db.add(
                Order(
                    id=first.aggregate_id,
                    order_number="MAI-" + uuid4().hex[:20],
                    user_id=first.envelope["payload"]["user_id"],
                    slot_id=slot.id,
                    total_amount=12000,
                    status=OrderStatus.PREPARING if versions > 1 else OrderStatus.PENDING,
                    version=versions,
                )
            )
            await db.flush()
            for version in range(1, versions + 1):
                envelope = json.loads(json.dumps(first.envelope))
                stamp = first.occurred_at - timedelta(seconds=version)
                envelope["event_id"] = str(uuid4())
                envelope["occurred_at"] = stamp.isoformat().replace("+00:00", "Z")
                envelope["payload"]["order_version"] = version
                if version > 1:
                    envelope["event_type"] = "ORDER_STATUS_UPDATED"
                    envelope["payload"].update(status="PREPARING", previous_status="PENDING")
                row = OutboxEvent(
                    event_id=envelope["event_id"],
                    aggregate_id=first.aggregate_id,
                    aggregate_version=version,
                    event_type=envelope["event_type"],
                    envelope=envelope,
                    occurred_at=stamp,
                )
                db.add(row)
                rows.append(row)
            await db.flush()
            if rollback:
                await db.rollback()
    return rows


def test_guard_excludes_second_worker_and_releases_on_close(integration_settings) -> None:
    async def run() -> None:
        first, second = store_for(integration_settings), store_for(integration_settings)
        try:
            await first.acquire()
            with pytest.raises(AlreadyRunning):
                await second.acquire()
            await second.close()
            await first.check_guard()
            await first.close()
            third = store_for(integration_settings)
            try:
                await third.acquire()
                await third.check_guard()
            finally:
                await third.close()
        finally:
            await first.close()
            await second.close()

    asyncio.run(run())


def test_versions_ignore_timestamp_order_and_send_has_no_sql_locks(integration_settings) -> None:
    async def run() -> None:
        store = store_for(integration_settings)
        sent = []

        class Publisher:
            async def publish(self, key: bytes, value: bytes) -> None:
                async with store.database.sessions() as db, db.begin():
                    assert (
                        await db.scalar(
                            text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE datname=current_database() "
                                "AND state='idle in transaction'"
                            )
                        )
                        == 0
                    )
                    await db.execute(text("SELECT id FROM orders FOR UPDATE NOWAIT"))
                    await db.execute(text("SELECT id FROM time_slots FOR UPDATE NOWAIT"))
                sent.append(json.loads(value)["payload"]["order_version"])

        try:
            await seed(store)
            await store.acquire()
            relay = Relay(store, Publisher(), integration_settings)
            assert await relay.publish_next()
            assert await relay.publish_next()
            assert not await relay.publish_next()
            assert sent == [1, 2]
        finally:
            await store.close()

    asyncio.run(run())


def test_rollback_has_nothing_to_publish(integration_settings) -> None:
    async def run() -> None:
        store = store_for(integration_settings)
        try:
            await seed(store, rollback=True)
            await store.acquire()
            assert await store.next_event() is None
            async with store.database.sessions() as db:
                assert await db.scalar(select(func.count()).select_from(Order)) == 0
        finally:
            await store.close()

    asyncio.run(run())


def test_real_guard_session_loss_cancels_blocked_send(integration_settings) -> None:
    async def run() -> None:
        store = store_for(integration_settings)
        await seed(store)
        started = asyncio.Event()
        stopped = asyncio.Event()
        sent = []

        class Publisher:
            async def start(self) -> None:
                pass

            async def publish(self, key: bytes, value: bytes) -> None:
                sent.append(json.loads(value))
                started.set()
                await asyncio.Event().wait()

            async def stop(self) -> None:
                stopped.set()

        settings = integration_settings.model_copy(update={"outbox_guard_interval_seconds": 0.01})
        worker = asyncio.create_task(serve(store, Publisher(), settings, asyncio.Event()))
        await asyncio.wait_for(started.wait(), timeout=5)
        async with store.database.engine.begin() as conn:
            assert await conn.scalar(
                text("SELECT pg_terminate_backend(:pid)"), {"pid": store.guard_pid}
            )
        with pytest.raises(ExceptionGroup) as failure:
            await asyncio.wait_for(worker, timeout=5)
        assert any(isinstance(e, GuardLost) for e in failure.value.exceptions)
        assert stopped.is_set() and len(sent) == 1
        replacement = store_for(integration_settings)
        try:
            await replacement.acquire()
            row = await replacement.next_event()
            assert row is not None and row.version == 1
        finally:
            await replacement.close()

    asyncio.run(run())


def test_kafka_ack_before_mark_crash_replays_stable_envelope(integration_settings) -> None:
    servers = os.getenv("MAI_TEST_KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        pytest.skip("Set MAI_TEST_KAFKA_BOOTSTRAP_SERVERS to run real Kafka recovery checks")

    async def run() -> None:
        topic = "mai-test-outbox-" + uuid4().hex
        settings = integration_settings.model_copy(
            update={"kafka_bootstrap_servers": servers, "outbox_topic": topic}
        )
        admin = AIOKafkaAdminClient(bootstrap_servers=servers)
        await admin.start()
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=servers,
            group_id="mai-test-" + uuid4().hex,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
        )
        store = store_for(settings)
        publisher = KafkaPublisher(settings)
        try:
            await admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)])
            await seed(store)
            await store.acquire()
            await publisher.start()
            await consumer.start()
            relay = Relay(store, publisher, settings)
            row = await store.next_event()
            assert row is not None
            # Inject process loss after real broker ACK and before the local DB mark.
            await publisher.publish(str(row.aggregate_id).encode(), relay.serialize(row))
            await publisher.stop()
            await store.close()
            store = store_for(settings)
            publisher = KafkaPublisher(settings)
            await store.acquire()
            await publisher.start()
            relay = Relay(store, publisher, settings)
            assert await relay.publish_next()
            assert await relay.publish_next()
            assert not await relay.publish_next()
            records = [await asyncio.wait_for(consumer.getone(), timeout=15) for _ in range(3)]
            bodies = [json.loads(r.value) for r in records]
            assert bodies[0] == bodies[1] == row.envelope
            assert [b["payload"]["order_version"] for b in bodies] == [1, 1, 2]
            assert all(r.key == str(row.aggregate_id).encode() for r in records)
            async with store.database.sessions() as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(OutboxEvent)
                        .where(OutboxEvent.published_at.is_(None))
                    )
                    == 0
                )
        finally:
            await publisher.stop()
            await store.close()
            await consumer.stop()
            await admin.delete_topics([topic])
            await admin.close()

    asyncio.run(run())


def test_http_order_creation_continues_while_publication_is_blocked(
    integration_client, integration_settings, auth_keys
) -> None:
    from conftest import auth
    from test_order_integration import prepare, submit

    client = integration_client
    _, body, _ = prepare(client, auth_keys[0])
    headers = auth(auth_keys[0])
    assert submit(client, body, headers).status_code == 201

    async def run() -> None:
        store = store_for(integration_settings)
        started = asyncio.Event()

        class BlockedPublisher:
            async def publish(self, key: bytes, value: bytes) -> None:
                started.set()
                await asyncio.Event().wait()

        try:
            await store.acquire()
            task = asyncio.create_task(
                Relay(store, BlockedPublisher(), integration_settings).publish_next()
            )
            try:
                await asyncio.wait_for(started.wait(), 5)
                second = await asyncio.wait_for(asyncio.to_thread(submit, client, body, headers), 3)
                assert second.status_code == 201
                async with store.database.sessions() as db:
                    assert await db.scalar(select(func.count()).select_from(Order)) == 2
                    assert (
                        await db.scalar(
                            select(func.count())
                            .select_from(OutboxEvent)
                            .where(OutboxEvent.published_at.is_(None))
                        )
                        == 2
                    )
            finally:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
        finally:
            await store.close()

    asyncio.run(run())


def test_poison_row_remains_pending_and_is_not_skipped(integration_settings) -> None:
    from order_service.application.outbox import InvalidEvent

    async def run() -> None:
        store = store_for(integration_settings)
        publisher = AsyncMock()
        try:
            await seed(store)
            async with store.database.engine.begin() as connection:
                await connection.execute(
                    text("UPDATE outbox_events SET event_type='BROKEN' WHERE aggregate_version=1")
                )
            await store.acquire()
            with pytest.raises(InvalidEvent):
                await Relay(store, publisher, integration_settings).publish_next()
            publisher.publish.assert_not_awaited()
            row = await store.next_event()
            assert row is not None and row.version == 1
            async with store.database.sessions() as db:
                assert (
                    await db.scalar(
                        select(func.count())
                        .select_from(OutboxEvent)
                        .where(OutboxEvent.published_at.is_(None))
                    )
                    == 2
                )
        finally:
            await store.close()

    asyncio.run(run())


def test_standalone_worker_process_publishes_and_stops_cleanly(integration_settings) -> None:
    import signal
    import sys

    servers = os.getenv("MAI_TEST_KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        pytest.skip("Set MAI_TEST_KAFKA_BOOTSTRAP_SERVERS for the real worker process check")

    async def run() -> None:
        topic = "mai-test-outbox-cli-" + uuid4().hex
        admin = AIOKafkaAdminClient(bootstrap_servers=servers)
        await admin.start()
        store = store_for(integration_settings)
        consumer = AIOKafkaConsumer(
            topic, bootstrap_servers=servers, auto_offset_reset="earliest", enable_auto_commit=False
        )
        process = None
        try:
            await admin.create_topics([NewTopic(topic, num_partitions=1, replication_factor=1)])
            await seed(store, versions=1)
            await consumer.start()
            environment = os.environ.copy()
            environment.update(
                APP_DATABASE_URL=integration_settings.database_url.get_secret_value(),
                APP_KAFKA_BOOTSTRAP_SERVERS=servers,
                APP_OUTBOX_TOPIC=topic,
            )
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "order_service.outbox",
                env=environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            record = await asyncio.wait_for(consumer.getone(), 15)
            assert json.loads(record.value)["payload"]["order_version"] == 1
            with pytest.raises(AlreadyRunning):
                await store.acquire()
            await store.close()
            process.send_signal(signal.SIGTERM)
            output, _ = await asyncio.wait_for(process.communicate(), 10)
            assert process.returncode == 0, output.decode()
            assert b"worker_ready" in output and b"event_published" in output
            assert environment["APP_DATABASE_URL"].encode() not in output
            await store.acquire()
            assert await store.next_event() is None
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
            await store.close()
            await consumer.stop()
            await admin.delete_topics([topic])
            await admin.close()

    asyncio.run(run())
