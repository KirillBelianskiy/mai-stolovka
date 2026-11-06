import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.exc import OperationalError
from test_outbox import Publisher, Store, event

from order_service.application.outbox import Relay, RetryablePublication
from order_service.config import Settings
from order_service.outbox import dispatch, report_backlog


def test_ack_and_durable_mark_have_separate_counters() -> None:
    async def run() -> None:
        store = Store(event())
        store.mark_error = True
        relay = Relay(store, Publisher(store), Settings())
        with pytest.raises(RuntimeError, match="crash after ACK"):
            await relay.publish_next()
        assert relay.stats.attempts == 1
        assert relay.stats.acks == 1
        assert relay.stats.published == 0
        assert relay.stats.last_success is None
        store.mark_error = False
        assert await relay.publish_next()
        assert relay.stats.attempts == 2 and relay.stats.acks == 2
        assert relay.stats.published == 1 and relay.stats.last_success is not None
        assert relay.stats.ack_latency_ms >= 0
        assert not await relay.publish_next()
        assert relay.stats.attempts == 2

    asyncio.run(run())


def test_broker_failure_never_counts_as_ack_or_publication() -> None:
    async def run() -> None:
        publisher = AsyncMock()
        publisher.publish.side_effect = RuntimeError("private broker endpoint")
        relay = Relay(Store(event()), publisher, Settings())
        with pytest.raises(RuntimeError):
            await relay.publish_next()
        assert relay.stats.attempts == 1
        assert relay.stats.acks == 0 and relay.stats.published == 0

    asyncio.run(run())


def test_backlog_report_contains_counts_and_age_without_envelopes(caplog) -> None:
    async def run() -> None:
        store = AsyncMock()
        store.backlog.return_value = (3, 65.5)
        relay = Relay(store, AsyncMock(), Settings())
        stop = asyncio.Event()

        async def finish(*args) -> None:
            stop.set()

        with patch("order_service.outbox.wait_or_stop", side_effect=finish):
            await report_backlog(store, relay.stats, Settings(), stop)
        assert "pending_count=3" in caplog.text
        assert "oldest_pending_seconds=65.500" in caplog.text
        assert "backlog_alert=true" in caplog.text
        assert "published_total=0" in caplog.text

    with caplog.at_level(logging.INFO, logger="order-outbox"):
        asyncio.run(run())


def test_monitoring_failure_is_sanitized_and_does_not_publish(caplog) -> None:
    async def run() -> None:
        store = AsyncMock()
        store.backlog.side_effect = OperationalError("SECRET URL", {}, Exception("SECRET"))
        relay = Relay(store, AsyncMock(), Settings())
        stop = asyncio.Event()

        async def finish(*args) -> None:
            stop.set()

        with patch("order_service.outbox.wait_or_stop", side_effect=finish):
            await report_backlog(store, relay.stats, Settings(), stop)
        store.mark_published.assert_not_awaited()
        assert "backlog_unavailable error_class=OperationalError" in caplog.text
        assert "SECRET" not in caplog.text

    asyncio.run(run())


def test_monitoring_wait_is_bounded_and_shutdown_interruptible() -> None:
    async def run() -> None:
        store = AsyncMock()

        async def stuck():
            await asyncio.Event().wait()

        store.backlog.side_effect = stuck
        relay = Relay(store, AsyncMock(), Settings())
        stop = asyncio.Event()
        settings = Settings(readiness_timeout_seconds=0.01, outbox_metrics_interval_seconds=0.01)
        task = asyncio.create_task(report_backlog(store, relay.stats, settings, stop))
        await asyncio.sleep(0.03)
        stop.set()
        await asyncio.wait_for(task, timeout=0.1)

    asyncio.run(run())


def test_repeated_failures_raise_retry_alert_after_threshold(caplog) -> None:
    async def run() -> None:
        store = AsyncMock()
        store.next_event.side_effect = RetryablePublication("private endpoint")
        relay = Relay(store, AsyncMock(), Settings())
        stop = asyncio.Event()
        waits = 0

        async def finish(*args) -> None:
            nonlocal waits
            waits += 1
            if waits == 2:
                stop.set()

        with (
            patch("order_service.outbox.wait_or_stop", side_effect=finish),
            patch("order_service.outbox.monotonic", side_effect=[100.0, 401.0], create=True),
        ):
            await dispatch(relay, Settings(), stop)
        assert relay.stats.retries == 2
        assert "retry_alert=true" in caplog.text
        assert "private endpoint" not in caplog.text

    asyncio.run(run())
