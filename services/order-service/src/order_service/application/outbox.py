import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from time import monotonic
from typing import Any, Protocol
from uuid import UUID

from jsonschema import Draft202012Validator, FormatChecker  # type: ignore[import-untyped]
from jsonschema.exceptions import ValidationError  # type: ignore[import-untyped]

from order_service.config import Settings

logger = logging.getLogger("order-outbox")


class InvalidEvent(RuntimeError):
    pass


class AmbiguousPublication(RuntimeError):
    pass


class RetryablePublication(RuntimeError):
    pass


@dataclass(frozen=True)
class PendingEvent:
    event_id: UUID
    aggregate_id: UUID
    version: int
    event_type: str
    occurred_at: datetime
    envelope: dict[str, Any]


class EventStore(Protocol):
    async def check_guard(self) -> None: ...
    async def next_event(self) -> PendingEvent | None: ...
    async def mark_published(self, event: PendingEvent) -> None: ...


class Publisher(Protocol):
    async def publish(self, key: bytes, value: bytes) -> None: ...


@dataclass
class PublicationStats:
    """Process-local counters; a broker ACK and a durable mark are distinct events."""

    attempts: int = 0
    acks: int = 0
    published: int = 0
    retries: int = 0
    ack_latency_ms: float = 0.0
    last_success: datetime | None = None


class Relay:
    def __init__(self, store: EventStore, publisher: Publisher, settings: Settings) -> None:
        self.store = store
        self.publisher = publisher
        self.settings = settings
        self.stats = PublicationStats()
        schema = json.loads(files("order_service").joinpath("resources/events-v1.json").read_text())
        self.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def serialize(self, row: PendingEvent) -> bytes:
        try:
            self.validator.validate(row.envelope)
            body = row.envelope
            if (
                body["event_id"] != str(row.event_id)
                or body["aggregate_id"] != str(row.aggregate_id)
                or body["event_type"] != row.event_type
                or body["payload"]["order_version"] != row.version
                or datetime.fromisoformat(body["occurred_at"]) != row.occurred_at
            ):
                raise InvalidEvent("Stored event metadata mismatch")
            return json.dumps(
                body, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        except (ValidationError, ValueError, TypeError, KeyError):
            raise InvalidEvent("Stored event does not match v1") from None

    async def publish_next(self) -> bool:
        await self.store.check_guard()
        row = await self.store.next_event()
        if row is None:
            return False
        logger.info(
            "publication_attempt event_id=%s aggregate_id=%s order_version=%s",
            row.event_id,
            row.aggregate_id,
            row.version,
        )
        value = self.serialize(row)
        await self.store.check_guard()
        self.stats.attempts += 1
        started = monotonic()
        try:
            async with asyncio.timeout(self.settings.outbox_send_timeout_seconds):
                await self.publisher.publish(str(row.aggregate_id).encode("utf-8"), value)
        except TimeoutError:
            raise AmbiguousPublication("Send deadline exceeded; event remains pending") from None
        self.stats.acks += 1
        self.stats.ack_latency_ms = (monotonic() - started) * 1000
        await self.store.check_guard()
        await self.store.mark_published(row)
        self.stats.published += 1
        self.stats.last_success = datetime.now(UTC)
        logger.info("event_published event_id=%s", row.event_id)
        return True
