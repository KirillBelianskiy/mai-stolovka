"""Explicit durable Kafka ingestion; never starts with HTTP and never sends to Telegram."""

import asyncio
import logging
import os
import signal
from typing import Any

from aiokafka import AIOKafkaConsumer, ConsumerRebalanceListener, TopicPartition  # type: ignore[import-untyped]
from aiokafka.admin import AIOKafkaAdminClient  # type: ignore[import-untyped]
from aiokafka.errors import NoOffsetForPartitionError  # type: ignore[import-untyped]

from notification_service.config import Settings
from notification_service.infrastructure.inbox import InboxStore, Record, RecoveryRequired

logger = logging.getLogger("notification-inbox")


async def process_record(store: Any, consumer: Any, message: Any) -> str:
    """Return only after durable ownership; caller serializes partition processing/revocation."""
    tp = TopicPartition(message.topic, message.partition)
    await store.check_guard()
    outcome: str = await store.ingest(
        Record(message.topic, message.partition, message.offset, message.key, message.value)
    )
    await store.check_guard()
    if tp not in consumer.assignment():
        raise RecoveryRequired("assignment_lost_before_commit")
    await consumer.commit({tp: message.offset + 1})
    return outcome


class Assignments(ConsumerRebalanceListener):  # type: ignore[misc]
    def __init__(self, store: InboxStore, consumer: Any, settings: Settings) -> None:
        self.store, self.consumer, self.settings = store, consumer, settings
        self.lock = asyncio.Lock()
        self.active: set[Any] = set()
        self.error: BaseException | None = None
        self.ready = asyncio.Event()
        self.generation = 0

    async def on_partitions_revoked(self, partitions: set[Any]) -> None:
        async with self.lock:
            self.ready.clear()
            self.generation += 1
            self.active.difference_update(partitions)

    async def on_partitions_assigned(self, partitions: set[Any]) -> None:
        async with self.lock:
            try:
                async with asyncio.timeout(self.settings.inbox_operation_timeout_seconds):
                    await self.store.check_guard()
                    begins = await self.consumer.beginning_offsets(partitions)
                    ends = await self.consumer.end_offsets(partitions)
                    for tp in sorted(partitions, key=lambda item: (item.topic, item.partition)):
                        committed = await self.consumer.committed(tp)
                        start = await self.store.initialize(
                            tp.topic, tp.partition, begins[tp], ends[tp], committed
                        )
                        self.consumer.seek(tp, start)
                    self.active.update(partitions)
                logger.info("partitions_ready count=%s", len(partitions))
                self.generation += 1
                self.ready.set()
            except Exception as error:
                self.error = error
                self.ready.set()
                self.consumer.pause(*partitions)
                logger.error("partition_recovery_required error_class=%s", type(error).__name__)


async def consume(
    store: InboxStore,
    consumer: Any,
    assignments: Assignments,
    settings: Settings,
    stop: asyncio.Event,
) -> None:
    while not stop.is_set():
        if assignments.error is not None:
            raise RecoveryRequired("assignment_recovery_required")
        if not assignments.ready.is_set():
            try:
                await asyncio.wait_for(assignments.ready.wait(), timeout=0.5)
            except TimeoutError:
                continue
            continue
        generation = assignments.generation
        try:
            messages = await consumer.getmany(timeout_ms=500, max_records=1)
        except NoOffsetForPartitionError:
            # Retry a stale position error only across an observed assignment change.
            # The callback selects a verified position; no fallback offset is invented.
            if not assignments.ready.is_set() or generation != assignments.generation:
                continue
            raise
        for tp, records in messages.items():
            for message in records:
                async with assignments.lock:
                    if stop.is_set():
                        return
                    if tp not in assignments.active:
                        continue
                    async with asyncio.timeout(settings.inbox_operation_timeout_seconds):
                        outcome = await process_record(store, consumer, message)
                    logger.info(
                        "record_owned topic=%s partition=%s offset=%s outcome=%s",
                        message.topic,
                        message.partition,
                        message.offset,
                        outcome,
                    )


async def monitor(store: InboxStore, stop: asyncio.Event) -> None:
    while not stop.is_set():
        await store.check_guard()
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.5)
        except TimeoutError:
            pass


async def serve(settings: Settings, stop: asyncio.Event) -> None:
    if settings.database_url is None:
        raise ValueError("Inbox requires APP_DATABASE_URL")
    store = InboxStore(
        settings.database_url.get_secret_value(),
        settings.inbox_group,
        settings.readiness_timeout_seconds,
    )
    consumer = AIOKafkaConsumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.inbox_group,
        enable_auto_commit=False,
        auto_offset_reset="none",
        client_id="mai-notification-inbox",
        max_poll_records=1,
        max_poll_interval_ms=60000,
        request_timeout_ms=10000,
    )
    assignments = Assignments(store, consumer, settings)
    try:
        async with asyncio.timeout(settings.inbox_operation_timeout_seconds):
            await store.acquire()
            admin = AIOKafkaAdminClient(bootstrap_servers=settings.kafka_bootstrap_servers)
            try:
                await admin.start()
                if settings.inbox_topic not in await admin.list_topics():
                    raise RecoveryRequired("topic_not_provisioned")
            finally:
                await admin.close()
            consumer.subscribe([settings.inbox_topic], listener=assignments)
            await consumer.start()
        async with asyncio.TaskGroup() as group:
            group.create_task(monitor(store, stop))
            group.create_task(consume(store, consumer, assignments, settings, stop))
    finally:
        # Hold the PG guard until Kafka background tasks are confirmed stopped.
        try:
            async with asyncio.timeout(settings.inbox_shutdown_timeout_seconds):
                await consumer.stop()
            async with asyncio.timeout(settings.inbox_shutdown_timeout_seconds):
                await store.close()
        except Exception:
            logger.critical("unsafe_cleanup process_termination_required=true")
            os._exit(2)


async def main_async() -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    try:
        settings = Settings()
        await serve(settings, stop)
        return 0
    except Exception as error:
        errors = error.exceptions if isinstance(error, ExceptionGroup) else (error,)
        logger.error(
            "worker_stopped error_classes=%s", ",".join(type(item).__name__ for item in errors)
        )
        return 1


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    for name in ("aiokafka", "sqlalchemy", "asyncpg"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
