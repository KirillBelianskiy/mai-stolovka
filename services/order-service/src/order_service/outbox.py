"""Explicit Outbox worker entrypoint; never started by the HTTP application."""

import asyncio
import logging
import os
import random
import signal

from sqlalchemy.exc import SQLAlchemyError

from order_service.application.outbox import Relay, RetryablePublication
from order_service.config import Settings
from order_service.infrastructure.kafka import KafkaPublisher
from order_service.infrastructure.outbox import PostgresOutbox

logger = logging.getLogger("order-outbox")


class UnsafeShutdown(RuntimeError):
    pass


async def wait_or_stop(stop: asyncio.Event, seconds: float) -> None:
    try:
        await asyncio.wait_for(stop.wait(), timeout=seconds)
    except TimeoutError:
        pass


async def dispatch(relay: Relay, settings: Settings, stop: asyncio.Event) -> None:
    failures = 0
    while not stop.is_set():
        try:
            published = await relay.publish_next()
            failures = 0
            if not published:
                await wait_or_stop(stop, settings.outbox_poll_seconds)
        except (RetryablePublication, SQLAlchemyError) as error:
            failures = min(failures + 1, 6)
            delay = random.uniform(0, min(30, 2 ** (failures - 1)))
            logger.warning("publication_retry error_class=%s", type(error).__name__)
            await wait_or_stop(stop, delay)


async def monitor(store: PostgresOutbox, settings: Settings, stop: asyncio.Event) -> None:
    while not stop.is_set():
        await store.check_guard()
        await wait_or_stop(stop, settings.outbox_guard_interval_seconds)


async def serve(
    store: PostgresOutbox, publisher: KafkaPublisher, settings: Settings, stop: asyncio.Event
) -> None:
    try:
        await store.acquire()
        async with asyncio.timeout(settings.outbox_send_timeout_seconds):
            await publisher.start()
        await store.check_guard()
        logger.info("worker_ready")
        async with asyncio.TaskGroup() as group:
            group.create_task(monitor(store, settings, stop))
            group.create_task(dispatch(Relay(store, publisher, settings), settings, stop))
    finally:
        # Keep the session guard until producer shutdown is confirmed. CLI hard-exits on timeout.
        try:
            async with asyncio.timeout(settings.outbox_shutdown_timeout_seconds):
                await publisher.stop()
        except Exception:
            raise UnsafeShutdown("Producer shutdown was not confirmed") from None
        try:
            async with asyncio.timeout(settings.outbox_shutdown_timeout_seconds):
                await store.close()
        except Exception:
            raise UnsafeShutdown("Database cleanup was not confirmed") from None


async def main_async() -> int:
    try:
        settings = Settings()
        if settings.database_url is None:
            raise ValueError("Worker requires APP_DATABASE_URL")
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, stop.set)
        store = PostgresOutbox(
            settings.database_url.get_secret_value(), settings.readiness_timeout_seconds
        )
        publisher = KafkaPublisher(settings)
        await serve(store, publisher, settings, stop)
        return 0
    except UnsafeShutdown:
        logger.critical("unsafe_worker_cleanup process_termination_required")
        # Avoid asyncio.run waiting indefinitely on producer tasks after an ambiguous cleanup.
        os._exit(2)
    except Exception as error:
        errors = error.exceptions if isinstance(error, ExceptionGroup) else (error,)
        logger.error("worker_stopped error_classes=%s", ",".join(type(e).__name__ for e in errors))
        return 1


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(name)s %(levelname)s %(message)s")
    # Third-party exception strings can include connection parameters; use our sanitized events.
    logging.getLogger("aiokafka").setLevel(logging.CRITICAL)
    logging.getLogger("sqlalchemy").setLevel(logging.CRITICAL)
    raise SystemExit(asyncio.run(main_async()))


if __name__ == "__main__":
    main()
