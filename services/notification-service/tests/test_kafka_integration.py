import asyncio
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from test_events import event
from test_inbox_integration import count, run_test

from notification_service.infrastructure.inbox import InboxStore, RecoveryRequired
from notification_service.infrastructure.models import Inbox, Obligation, Receipt
from notification_service.ingest import process_record

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[3]


def kafka_cli(*args):
    result = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "kafka",
            "/opt/kafka/bin/kafka-consumer-groups.sh",
            "--bootstrap-server",
            "kafka:29092",
            *args,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
    )
    return result


def broker_test(test):
    servers = os.environ.get("MAI_TEST_KAFKA_BOOTSTRAP_SERVERS")
    if not servers:
        pytest.skip("Use the isolated PG/Kafka runner")
    group = "mai-test-inbox-" + uuid4().hex
    topic = "mai-test-inbox-" + uuid4().hex

    async def run(store):
        admin = AIOKafkaAdminClient(bootstrap_servers=servers)
        producer = AIOKafkaProducer(bootstrap_servers=servers, acks="all")
        try:
            await admin.start()
            await admin.create_topics([NewTopic(topic, 1, 1)])
            await producer.start()
            await test(store, producer, servers, topic, group)
        finally:
            try:
                await producer.stop()
            finally:
                try:
                    await admin.delete_topics([topic])
                finally:
                    await admin.close()
            groups = kafka_cli("--list")
            assert groups.returncode == 0
            if group in groups.stdout.splitlines():
                deleted = kafka_cli("--delete", "--group", group)
                assert deleted.returncode == 0, "Disposable group cleanup failed"

    run_test(run, group)


async def consumer_for(store, servers, topic):
    tp = TopicPartition(topic, 0)
    consumer = AIOKafkaConsumer(
        bootstrap_servers=servers,
        group_id=store.group,
        enable_auto_commit=False,
        auto_offset_reset="none",
        request_timeout_ms=10000,
    )
    consumer.assign([tp])
    await consumer.start()
    try:
        begin, end = (
            (await consumer.beginning_offsets([tp]))[tp],
            (await consumer.end_offsets([tp]))[tp],
        )
        start = await store.initialize(topic, 0, begin, end, await consumer.committed(tp))
        consumer.seek(tp, start)
    except BaseException:
        await consumer.stop()
        raise
    return consumer, tp


def test_crash_after_database_commit_replays_and_poison_commits_only_after_quarantine():
    async def check(store, producer, servers, topic, group):
        body = event()
        await producer.send_and_wait(
            topic, key=body["aggregate_id"].encode(), value=json.dumps(body).encode()
        )
        await store.acquire()
        consumer, tp = await consumer_for(store, servers, topic)
        try:
            message = await asyncio.wait_for(consumer.getone(), 10)
            from notification_service.infrastructure.inbox import Record

            await store.ingest(
                Record(message.topic, message.partition, message.offset, message.key, message.value)
            )
            assert await consumer.committed(tp) is None
            assert await store.position(topic, 0) == 1
            assert await count(store, Obligation) == 1
        finally:
            await consumer.stop()
        await store.close()
        restored = InboxStore(store.url, group, 2)
        try:
            await restored.acquire()
            consumer, tp = await consumer_for(restored, servers, topic)
            try:
                message = await asyncio.wait_for(consumer.getone(), 10)
                assert await process_record(restored, consumer, message) == "REPLAY"
                assert await consumer.committed(tp) == 1
                assert await count(restored, Obligation) == 1
                await producer.send_and_wait(topic, value=b"poison")
                assert (
                    await process_record(
                        restored, consumer, await asyncio.wait_for(consumer.getone(), 10)
                    )
                    == "QUARANTINED"
                )
                assert await consumer.committed(tp) == 2
                async with restored.sessions() as db:
                    poison = await db.scalar(
                        select(Receipt).where(Receipt.topic == topic, Receipt.offset == 1)
                    )
                    assert poison.protected_value == b"poison" and poison.reason == "malformed"
            finally:
                await consumer.stop()
        finally:
            await restored.close()

    broker_test(check)


def test_database_failure_at_n_prevents_committing_fetched_n_plus_one():
    async def check(store, producer, servers, topic, group):
        for _ in range(2):
            body = event()
            await producer.send_and_wait(
                topic, key=body["aggregate_id"].encode(), value=json.dumps(body).encode()
            )
        await store.acquire()
        consumer, tp = await consumer_for(store, servers, topic)
        try:
            async with store.engine.begin() as db:
                await db.execute(
                    text(
                        "ALTER TABLE source_receipts ADD CONSTRAINT reject_receipt "
                        "CHECK (false) NOT VALID"
                    )
                )
            try:
                first = await asyncio.wait_for(consumer.getone(), 10)
                second = await asyncio.wait_for(consumer.getone(), 10)
                assert (first.offset, second.offset) == (0, 1)
                with pytest.raises(IntegrityError):
                    await process_record(store, consumer, first)
                assert await consumer.committed(tp) is None
                assert await store.position(topic, 0) == 0 and await count(store, Inbox) == 0
            finally:
                async with store.engine.begin() as db:
                    await db.execute(
                        text("ALTER TABLE source_receipts DROP CONSTRAINT reject_receipt")
                    )
            consumer.seek(tp, 0)
            for _ in range(2):
                await process_record(store, consumer, await asyncio.wait_for(consumer.getone(), 10))
            assert await consumer.committed(tp) == 2
        finally:
            await consumer.stop()

    broker_test(check)


def test_standalone_singleton_guard_loss_restart_and_sigterm():
    async def check(store, producer, servers, topic, group):
        body = event()
        await producer.send_and_wait(
            topic, key=body["aggregate_id"].encode(), value=json.dumps(body).encode()
        )
        environment = {
            **os.environ,
            "APP_DATABASE_URL": store.url,
            "APP_INBOX_GROUP": group,
            "APP_INBOX_TOPIC": topic,
            "APP_KAFKA_BOOTSTRAP_SERVERS": servers,
        }
        children = []

        async def start():
            child = await asyncio.create_subprocess_exec(
                str(ROOT / "services/notification-service/.venv/bin/python"),
                "-m",
                "notification_service.ingest",
                cwd=ROOT / "services/notification-service",
                env=environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            children.append(child)
            return child

        try:
            first = await start()
            async with asyncio.timeout(20):
                while await store.position(topic, 0) != 1:
                    if first.returncode is not None:
                        raise AssertionError((await first.communicate())[1].decode())
                    await asyncio.sleep(0.05)
            second = await start()
            assert await asyncio.wait_for(second.wait(), 15) == 1
            async with store.engine.begin() as db:
                await db.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname=current_database() "
                        "AND application_name='notification-inbox-guard'"
                    )
                )
            assert await asyncio.wait_for(first.wait(), 15) == 1
            restarted = await start()
            async with asyncio.timeout(15):
                while True:
                    async with store.engine.connect() as db:
                        active = await db.scalar(
                            text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE datname=current_database() "
                                "AND application_name='notification-inbox-guard'"
                            )
                        )
                    if active:
                        break
                    await asyncio.sleep(0.05)
            restarted.terminate()
            assert await asyncio.wait_for(restarted.wait(), 15) == 0
            assert await count(store, Obligation) == 1
        finally:
            for child in children:
                if child.returncode is None:
                    child.kill()
                    await child.wait()

    broker_test(check)


def test_actual_broker_position_ahead_of_restored_database_stops():
    async def check(store, producer, servers, topic, group):
        for _ in range(2):
            body = event()
            await producer.send_and_wait(
                topic, key=body["aggregate_id"].encode(), value=json.dumps(body).encode()
            )
        consumer, tp = await consumer_for(store, servers, topic)
        try:
            await consumer.commit({tp: 2})
        finally:
            await consumer.stop()
        with pytest.raises(RecoveryRequired):
            await consumer_for(store, servers, topic)
        assert await store.position(topic, 0) == 0
        assert await count(store, Receipt) == 0

    broker_test(check)


def test_expired_real_kafka_position_never_resets_to_latest():
    async def check(store, producer, servers, topic, group):
        for _ in range(2):
            body = event()
            await producer.send_and_wait(
                topic, key=body["aggregate_id"].encode(), value=json.dumps(body).encode()
            )
        await store.acquire()
        consumer, tp = await consumer_for(store, servers, topic)
        try:
            for _ in range(2):
                await process_record(store, consumer, await asyncio.wait_for(consumer.getone(), 10))
            await consumer.commit({tp: 0})
        finally:
            await consumer.stop()
        assert topic.startswith("mai-test-inbox-")
        deletion = subprocess.run(
            [
                "docker",
                "compose",
                "exec",
                "-T",
                "kafka",
                "/opt/kafka/bin/kafka-delete-records.sh",
                "--bootstrap-server",
                "kafka:29092",
                "--offset-json-file",
                "/dev/stdin",
            ],
            input=json.dumps(
                {"partitions": [{"topic": topic, "partition": 0, "offset": 1}], "version": 1}
            ),
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=60,
        )
        assert deletion.returncode == 0, "Disposable retention probe failed"
        with pytest.raises(RecoveryRequired):
            await consumer_for(store, servers, topic)
        assert await store.position(topic, 0) == 2
        assert await count(store, Obligation) == 2

    broker_test(check)
