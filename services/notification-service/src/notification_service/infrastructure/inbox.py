import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from notification_service.domain.events import (
    MAX_RECORD_BYTES,
    Event,
    InvalidRecord,
    compatible,
    parse_event,
)
from notification_service.infrastructure.models import (
    Checkpoint,
    Inbox,
    Obligation,
    ObservedVersion,
    OrderObservation,
    Receipt,
)


class RecoveryRequired(RuntimeError):
    pass


@dataclass(frozen=True)
class Record:
    topic: str
    partition: int
    offset: int
    key: bytes | None
    value: bytes | None


def raw_hash(value: bytes | None) -> str:
    return hashlib.sha256(b"\x00" if value is None else b"\x01" + value).hexdigest()


class InboxStore:
    def __init__(self, url: str, group_id: str, timeout: float) -> None:
        self.group = group_id
        self.url = url
        self.timeout = timeout
        self.engine = create_async_engine(
            url,
            pool_pre_ping=True,
            pool_timeout=timeout,
            connect_args={
                "timeout": timeout,
                "command_timeout": 5,
                "server_settings": {"application_name": "notification-inbox"},
            },
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.guard: Any = None
        self.guard_pid: int | None = None
        self.guard_key = int.from_bytes(
            hashlib.sha256(("mai-notification:" + group_id).encode()).digest()[:8], "big"
        ) & ((1 << 63) - 1)
        self.guard_lock = asyncio.Lock()

    async def acquire(self) -> None:
        self.guard = await asyncpg.connect(
            self.url.replace("postgresql+asyncpg://", "postgresql://"),
            timeout=self.timeout,
            command_timeout=self.timeout,
            server_settings={"application_name": "notification-inbox-guard"},
        )
        self.guard_pid = await self.guard.fetchval("SELECT pg_backend_pid()")
        if not await self.guard.fetchval("SELECT pg_try_advisory_lock($1)", self.guard_key):
            raise RecoveryRequired("worker_already_running")

    async def check_guard(self) -> None:
        async with self.guard_lock:
            if self.guard is None or self.guard.is_closed():
                raise RecoveryRequired("guard_lost")
            row = await self.guard.fetchrow(
                "SELECT pg_backend_pid() AS pid, EXISTS (SELECT 1 FROM pg_locks "
                "WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted "
                "AND classid=$1 AND objid=$2 AND objsubid=1) AS held",
                self.guard_key >> 32,
                self.guard_key & 0xFFFFFFFF,
            )
            if row["pid"] != self.guard_pid or not row["held"]:
                raise RecoveryRequired("guard_lost")

    async def initialize(
        self, topic: str, partition: int, begin: int, end: int, committed: int | None
    ) -> int:
        async with self.sessions() as db, db.begin():
            checkpoint = await db.get(Checkpoint, (self.group, topic, partition))
            if checkpoint is None:
                if begin != 0 or committed not in (None, 0):
                    raise RecoveryRequired("missing_durable_history")
                await db.execute(
                    insert(Checkpoint)
                    .values(group_id=self.group, topic=topic, partition=partition, next_offset=0)
                    .on_conflict_do_nothing()
                )
                checkpoint = await db.get(
                    Checkpoint, (self.group, topic, partition), populate_existing=True
                )
            assert checkpoint is not None
            start = 0 if committed is None else committed
            if not begin <= start <= checkpoint.next_offset <= end:
                raise RecoveryRequired("offset_restore_gap")
            return start

    async def position(self, topic: str, partition: int) -> int | None:
        async with self.sessions() as db:
            row = await db.get(Checkpoint, (self.group, topic, partition))
            return row.next_offset if row else None

    async def ingest(self, record: Record) -> str:
        async with self.sessions() as db, db.begin():
            await db.execute(text("SET LOCAL lock_timeout='2000ms'"))
            await db.execute(text("SET LOCAL statement_timeout='5000ms'"))
            checkpoint = await db.scalar(
                select(Checkpoint)
                .where(
                    Checkpoint.group_id == self.group,
                    Checkpoint.topic == record.topic,
                    Checkpoint.partition == record.partition,
                )
                .with_for_update()
            )
            if checkpoint is None:
                raise RecoveryRequired("partition_not_initialized")
            key_hash, value_hash = raw_hash(record.key), raw_hash(record.value)
            previous = await db.get(
                Receipt, (self.group, record.topic, record.partition, record.offset)
            )
            if previous:
                if (previous.key_hash, previous.value_hash) != (key_hash, value_hash):
                    raise RecoveryRequired("source_content_changed")
                if checkpoint.next_offset <= record.offset:
                    raise RecoveryRequired("checkpoint_history_inconsistent")
                return "REPLAY"
            if record.offset < checkpoint.next_offset:
                raise RecoveryRequired("receipt_history_missing")
            outcome, reason, event_id = "QUARANTINED", None, None
            try:
                event = parse_event(record.key, record.value)
            except InvalidRecord as error:
                reason = str(error)
            else:
                event_id = event.event_id
                outcome, reason = await self._accept(db, event)
            db.add(
                Receipt(
                    group_id=self.group,
                    topic=record.topic,
                    partition=record.partition,
                    offset=record.offset,
                    key_hash=key_hash,
                    value_hash=value_hash,
                    event_id=event_id,
                    outcome=outcome,
                    reason=reason,
                    protected_value=(record.value or b"")[:MAX_RECORD_BYTES]
                    if outcome == "QUARANTINED"
                    else None,
                    truncated=bool(record.value and len(record.value) > MAX_RECORD_BYTES),
                )
            )
            checkpoint.next_offset = record.offset + 1
            await db.flush()
            return outcome

    async def _observation(self, db: AsyncSession, event: Event) -> OrderObservation:
        await db.execute(
            insert(OrderObservation)
            .values(
                order_id=event.order_id,
                identity_hash=event.identity_hash,
                user_id=event.user_id,
                version=0,
                status="UNKNOWN",
                frozen=False,
                gap_observed=False,
            )
            .on_conflict_do_nothing()
        )
        row = await db.scalar(
            select(OrderObservation)
            .where(OrderObservation.order_id == event.order_id)
            .with_for_update()
        )
        assert row is not None
        return row

    async def _freeze(self, db: AsyncSession, order_ids: list[UUID]) -> None:
        for order_id in sorted(set(order_ids)):
            row = await db.scalar(
                select(OrderObservation)
                .where(OrderObservation.order_id == order_id)
                .with_for_update()
            )
            if row is None:
                raise RecoveryRequired("observation_history_missing")
            row.frozen = True
            await db.execute(
                update(Obligation).where(Obligation.order_id == order_id).values(state="FROZEN")
            )

    async def _accept(self, db: AsyncSession, event: Event) -> tuple[str, str | None]:
        claimed = await db.scalar(
            insert(Inbox)
            .values(
                event_id=event.event_id,
                order_id=event.order_id,
                content_hash=event.content_hash,
                envelope=event.envelope,
                outcome="ACCEPTED",
            )
            .on_conflict_do_nothing()
            .returning(Inbox.event_id)
        )
        inbox = await db.get(Inbox, event.event_id)
        assert inbox is not None
        if claimed is None and inbox.content_hash == event.content_hash:
            return "DUPLICATE_ID", None
        # One consumer owns the group; row locks also serialize concurrent storage tests/partitions.
        if claimed is None:
            for order_id in sorted({event.order_id, inbox.order_id}):
                if order_id == event.order_id:
                    await self._observation(db, event)
                else:
                    old = await db.scalar(
                        select(OrderObservation)
                        .where(OrderObservation.order_id == order_id)
                        .with_for_update()
                    )
                    if old is None:
                        raise RecoveryRequired("observation_history_missing")
            await self._freeze(db, [event.order_id, inbox.order_id])
            return "QUARANTINED", "event_id_conflict"
        observation = await self._observation(db, event)
        reason = None
        if observation.frozen:
            reason = "order_frozen"
        elif observation.identity_hash != event.identity_hash:
            reason = "identity_conflict"
        versions = list(
            await db.scalars(
                select(ObservedVersion).where(ObservedVersion.order_id == event.order_id)
            )
        )
        same = next((row for row in versions if row.version == event.version), None)
        if not reason and same:
            if same.state_hash == event.state_hash:
                inbox.outcome = "DUPLICATE_VERSION"
                return inbox.outcome, None
            reason = "version_conflict"
        if not reason:
            for row in versions:
                old_event = parse_event(
                    str(event.order_id).encode(), json.dumps(row.envelope).encode()
                )
                if not compatible(old_event, event):
                    reason = "lifecycle_conflict"
                    break
        if reason:
            inbox.outcome = "QUARANTINED"
            await self._freeze(db, [event.order_id])
            return inbox.outcome, reason
        db.add(
            ObservedVersion(
                order_id=event.order_id,
                version=event.version,
                state_hash=event.state_hash,
                envelope=event.envelope,
            )
        )
        if event.version > 1 and not any(row.version == event.version - 1 for row in versions):
            observation.gap_observed = True
        if event.version > observation.version:
            observation.version, observation.status = event.version, event.status
        if observation.status in {"COMPLETED", "CANCELLED"}:
            await db.execute(
                update(Obligation)
                .where(Obligation.order_id == event.order_id, Obligation.state == "PENDING")
                .values(state="SUPPRESSED")
            )
            inbox.outcome = "NO_SEND"
        elif event.status == "READY" and event.version == observation.version:
            await db.flush()
            db.add(
                Obligation(
                    order_id=event.order_id,
                    version=event.version,
                    event_id=event.event_id,
                    user_id=event.user_id,
                    state="PENDING",
                )
            )
        else:
            inbox.outcome = "NO_SEND"
        return inbox.outcome, None

    async def close(self) -> None:
        try:
            if self.guard is not None:
                await self.guard.close(timeout=self.timeout)
        finally:
            await self.engine.dispose()
