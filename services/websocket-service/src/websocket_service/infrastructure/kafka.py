import asyncio
import logging
from collections.abc import Mapping
from typing import Protocol

from aiokafka import AIOKafkaConsumer, ConsumerRebalanceListener, TopicPartition  # type: ignore[import-untyped]
from aiokafka.admin import AIOKafkaAdminClient  # type: ignore[import-untyped]
from aiokafka.errors import KafkaError, OffsetOutOfRangeError  # type: ignore[import-untyped]

from websocket_service.application.hub import KitchenHub
from websocket_service.config import Settings
from websocket_service.domain.events import order_hint

logger = logging.getLogger(__name__)
BROKER_TIMEOUT = 10
PROBE_INTERVAL = 5


class Record(Protocol):
    @property
    def key(self) -> bytes | None: ...

    @property
    def value(self) -> bytes | None: ...

    @property
    def offset(self) -> int: ...


class Consumer(Protocol):
    def partitions_for_topic(self, topic: str) -> set[int] | None: ...

    async def beginning_offsets(
        self, partitions: set[TopicPartition]
    ) -> dict[TopicPartition, int]: ...

    async def end_offsets(self, partitions: set[TopicPartition]) -> dict[TopicPartition, int]: ...

    async def committed(self, partition: TopicPartition) -> int | None: ...

    def seek(self, partition: TopicPartition, offset: int) -> None: ...

    async def getmany(
        self, *, timeout_ms: int, max_records: int
    ) -> Mapping[TopicPartition, list[Record]]: ...

    async def commit(self, offsets: dict[TopicPartition, int]) -> None: ...


class RecoveryRequired(ValueError):
    """An operator must reconcile the Kafka stream or group position."""


class Assignments(ConsumerRebalanceListener):  # type: ignore[misc]
    def __init__(self, consumer: Consumer, hub: KitchenHub, topic: str) -> None:
        self.consumer = consumer
        self.hub = hub
        self.topic = topic
        self.active: set[TopicPartition] = set()
        self.generation = 0
        self.error: Exception | None = None

    async def on_partitions_revoked(self, partitions: set[TopicPartition]) -> None:
        self.hub.suspend()
        self.generation += 1
        self.active.clear()

    async def on_partitions_assigned(self, partitions: set[TopicPartition]) -> None:
        if self.error is not None:
            return
        expected = {
            TopicPartition(self.topic, number)
            for number in self.consumer.partitions_for_topic(self.topic) or ()
        }
        if not expected or partitions != expected:
            logger.warning("Kitchen Kafka requires a full single-instance assignment")
            return
        try:
            async with asyncio.timeout(BROKER_TIMEOUT):
                begins = await self.consumer.beginning_offsets(partitions)
                ends = await self.consumer.end_offsets(partitions)
                for partition in sorted(partitions):
                    committed = await self.consumer.committed(partition)
                    if committed is None:
                        self.consumer.seek(partition, ends[partition])
                    elif begins[partition] <= committed <= ends[partition]:
                        self.consumer.seek(partition, committed)
                    else:
                        raise RecoveryRequired(
                            f"Kitchen Kafka committed offset outside retained range: {partition}"
                        )
        except (KafkaError, TimeoutError, RecoveryRequired) as error:
            self.error = error
            return
        self.active = partitions.copy()
        self.hub.ready = True


async def consume(consumer: Consumer, assignments: Assignments, hub: KitchenHub) -> None:
    loop = asyncio.get_running_loop()
    next_probe = loop.time() + PROBE_INTERVAL
    while True:
        if assignments.error is not None:
            raise assignments.error
        generation = assignments.generation
        if not assignments.active:
            await asyncio.sleep(0.25)
            continue
        if loop.time() >= next_probe:
            async with asyncio.timeout(BROKER_TIMEOUT):
                await consumer.end_offsets(assignments.active.copy())
            next_probe = loop.time() + PROBE_INTERVAL
        try:
            messages = await consumer.getmany(timeout_ms=500, max_records=1)
        except OffsetOutOfRangeError as error:
            if generation != assignments.generation:
                continue
            raise RecoveryRequired("Kitchen Kafka position fell outside retained range") from error
        if generation != assignments.generation:
            continue
        for partition, records in messages.items():
            for record in records:
                if generation != assignments.generation or partition not in assignments.active:
                    break
                try:
                    order_id, version = order_hint(record.key, record.value)
                except (ValueError, RecursionError):
                    raise RecoveryRequired(
                        f"Invalid Kitchen Kafka record: {partition} offset={record.offset}"
                    ) from None
                await hub.publish_order_hint(order_id, version)
                async with asyncio.timeout(BROKER_TIMEOUT):
                    await consumer.commit({partition: record.offset + 1})


async def stop_consumer(consumer: AIOKafkaConsumer) -> None:
    # aiokafka 0.15 can propagate cancellation of a pending fetch from stop(),
    # before closing the broker connection. Isolate that from caller cancellation.
    results: list[None | BaseException] = await asyncio.gather(
        consumer.stop(), return_exceptions=True
    )
    result = results[0]
    if isinstance(result, asyncio.CancelledError):
        await consumer._client.close()
    elif isinstance(result, BaseException):
        raise result


async def run_consumer(settings: Settings, hub: KitchenHub) -> None:
    while True:
        consumer = AIOKafkaConsumer(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id=settings.kitchen_kafka_group,
            client_id="mai-kitchen",
            enable_auto_commit=False,
            auto_offset_reset="none",
            request_timeout_ms=BROKER_TIMEOUT * 1000,
        )
        assignments = Assignments(consumer, hub, settings.kitchen_kafka_topic)
        consumer.subscribe([settings.kitchen_kafka_topic], listener=assignments)
        try:
            async with asyncio.timeout(2 * BROKER_TIMEOUT):
                admin = AIOKafkaAdminClient(
                    bootstrap_servers=settings.kafka_bootstrap_servers,
                    request_timeout_ms=BROKER_TIMEOUT * 1000,
                )
                try:
                    await admin.start()
                    if settings.kitchen_kafka_topic not in await admin.list_topics():
                        logger.warning("Kitchen Kafka topic has not been provisioned")
                        raise TimeoutError
                finally:
                    await admin.close()
                await consumer.start()
            await consume(consumer, assignments, hub)
        except RecoveryRequired as error:
            logger.error("%s; resolve and restart the WebSocket service", error)
            return
        except (KafkaError, TimeoutError) as error:
            logger.warning("Kitchen Kafka temporarily unavailable: %s", type(error).__name__)
        finally:
            hub.suspend()
            await stop_consumer(consumer)
        await asyncio.sleep(2)
