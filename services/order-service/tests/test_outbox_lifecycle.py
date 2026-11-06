import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from aiokafka.errors import (
    KafkaConnectionError,
    RequestTimedOutError,
    TopicAuthorizationFailedError,
)
from sqlalchemy.exc import OperationalError
from test_outbox import Publisher, Store, event

from order_service.application.outbox import (
    AmbiguousPublication,
    InvalidEvent,
    Relay,
    RetryablePublication,
)
from order_service.config import Settings
from order_service.infrastructure.kafka import KafkaPublisher
from order_service.outbox import UnsafeShutdown, dispatch, serve


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (KafkaConnectionError(), RetryablePublication),
        (RequestTimedOutError(), AmbiguousPublication),
        (TopicAuthorizationFailedError(), InvalidEvent),
    ],
)
def test_broker_errors_have_explicit_retry_boundary(error, expected) -> None:
    async def run() -> None:
        producer = AsyncMock()
        producer.send_and_wait.side_effect = error
        with patch(
            "order_service.infrastructure.kafka.AIOKafkaProducer", return_value=producer
        ) as ctor:
            publisher = KafkaPublisher(Settings())
            assert ctor.call_args.kwargs["enable_idempotence"] is True
            assert ctor.call_args.kwargs["acks"] == "all"
            with pytest.raises(expected):
                await publisher.publish(b"order", b"event")

    asyncio.run(run())


def test_missing_topic_is_not_created_by_startup() -> None:
    async def run() -> None:
        producer, admin = AsyncMock(), AsyncMock()
        admin.list_topics.return_value = []
        with (
            patch("order_service.infrastructure.kafka.AIOKafkaProducer", return_value=producer),
            patch("order_service.infrastructure.kafka.AIOKafkaAdminClient", return_value=admin),
        ):
            publisher = KafkaPublisher(Settings())
            with pytest.raises(InvalidEvent):
                await publisher.start()
            producer.start.assert_not_awaited()
            admin.create_topics.assert_not_called()
            admin.close.assert_awaited_once()

    asyncio.run(run())


def test_failed_mark_retries_same_head_then_stops() -> None:
    async def run() -> None:
        stop = asyncio.Event()

        class FailOnceStore(Store):
            async def mark_published(self, row) -> None:
                if not self.mark_error:
                    self.mark_error = True
                    raise OperationalError("mark", {}, Exception("injected"))
                self.marked = True
                stop.set()

        store = FailOnceStore(event())
        publisher = Publisher(store)
        with patch("order_service.outbox.random.uniform", return_value=0):
            await asyncio.wait_for(
                dispatch(Relay(store, publisher, Settings()), Settings(), stop), 1
            )
        assert store.marked and publisher.sent[0] == publisher.sent[1]

    asyncio.run(run())


def test_shutdown_confirms_producer_stop_before_guard_release() -> None:
    async def run() -> None:
        actions = []
        store, publisher = AsyncMock(), AsyncMock()
        store.acquire.side_effect = lambda: actions.append("guard_acquired")
        publisher.start.side_effect = lambda: actions.append("producer_started")
        publisher.stop.side_effect = lambda: actions.append("producer_stopped")
        store.close.side_effect = lambda: actions.append("guard_released")
        stop = asyncio.Event()
        stop.set()
        await serve(store, publisher, Settings(), stop)
        assert actions == [
            "guard_acquired",
            "producer_started",
            "producer_stopped",
            "guard_released",
        ]

    asyncio.run(run())


def test_ambiguous_cleanup_keeps_guard_for_process_termination() -> None:
    async def run() -> None:
        store, publisher = AsyncMock(), AsyncMock()

        async def stuck() -> None:
            await asyncio.Event().wait()

        publisher.stop.side_effect = stuck
        stop = asyncio.Event()
        stop.set()
        settings = Settings(outbox_shutdown_timeout_seconds=0.01)
        with pytest.raises(UnsafeShutdown):
            await asyncio.wait_for(serve(store, publisher, settings, stop), 1)
        store.close.assert_not_awaited()

    asyncio.run(run())


def test_guard_cleanup_is_also_bounded() -> None:
    async def run() -> None:
        store, publisher = AsyncMock(), AsyncMock()

        async def stuck() -> None:
            await asyncio.Event().wait()

        store.close.side_effect = stuck
        stop = asyncio.Event()
        stop.set()
        settings = Settings(outbox_shutdown_timeout_seconds=0.01)
        with pytest.raises(UnsafeShutdown):
            await asyncio.wait_for(serve(store, publisher, settings, stop), 0.1)
        publisher.stop.assert_awaited_once()

    asyncio.run(run())
