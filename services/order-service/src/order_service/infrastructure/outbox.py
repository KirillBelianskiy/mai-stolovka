import asyncio

from sqlalchemy import exists, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.orm import aliased
from sqlalchemy.pool import NullPool

from order_service.application.outbox import InvalidEvent, PendingEvent
from order_service.infrastructure.database import Database
from order_service.infrastructure.models import OutboxEvent

# Stable positive bigint namespace; identical for every relay using this database.
GUARD_KEY = 0x4D41494F55544258


class GuardLost(RuntimeError):
    pass


class AlreadyRunning(RuntimeError):
    pass


class PostgresOutbox:
    def __init__(self, url: str, timeout: float) -> None:
        self.database = Database(url, timeout)
        self.guard_engine = create_async_engine(
            url,
            isolation_level="AUTOCOMMIT",
            poolclass=NullPool,
            connect_args={
                "timeout": timeout,
                "command_timeout": timeout,
                "server_settings": {"application_name": "order-outbox-guard"},
            },
        )
        self.guard_connection: AsyncConnection | None = None
        self.guard_pid: int | None = None
        self.timeout = timeout
        self.guard_query_lock = asyncio.Lock()

    async def acquire(self) -> None:
        self.guard_connection = await self.guard_engine.connect()
        self.guard_pid = await self.guard_connection.scalar(text("SELECT pg_backend_pid()"))
        acquired = await self.guard_connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": GUARD_KEY}
        )
        if not acquired:
            raise AlreadyRunning("Another Outbox worker owns the guard")

    async def check_guard(self) -> None:
        async with self.guard_query_lock:
            connection = self.guard_connection
            if connection is None or connection.closed or connection.invalidated:
                raise GuardLost("Outbox guard session is unavailable")
            try:
                async with asyncio.timeout(self.timeout):
                    row = (
                        (
                            await connection.execute(
                                text(
                                    "SELECT pg_backend_pid() AS pid, EXISTS ("
                                    "SELECT 1 FROM pg_locks WHERE pid = pg_backend_pid() "
                                    "AND locktype = 'advisory' AND granted "
                                    "AND classid = :high AND objid = :low AND objsubid = 1) AS held"
                                ),
                                {"high": GUARD_KEY >> 32, "low": GUARD_KEY & 0xFFFFFFFF},
                            )
                        )
                        .mappings()
                        .one()
                    )
                if row["pid"] != self.guard_pid or not row["held"]:
                    raise GuardLost("Outbox guard ownership changed")
            except GuardLost:
                raise
            except Exception:
                raise GuardLost("Outbox guard check failed") from None

    async def next_event(self) -> PendingEvent | None:
        lower = aliased(OutboxEvent)
        async with self.database.sessions() as db:
            row = await db.scalar(
                select(OutboxEvent)
                .where(
                    OutboxEvent.published_at.is_(None),
                    ~exists(
                        select(lower.event_id).where(
                            lower.aggregate_id == OutboxEvent.aggregate_id,
                            lower.aggregate_version < OutboxEvent.aggregate_version,
                            lower.published_at.is_(None),
                        )
                    ),
                )
                .order_by(
                    OutboxEvent.occurred_at,
                    OutboxEvent.aggregate_id,
                    OutboxEvent.aggregate_version,
                )
                .limit(1)
            )
            if row is None:
                return None
            return PendingEvent(
                row.event_id,
                row.aggregate_id,
                row.aggregate_version,
                row.event_type,
                row.occurred_at,
                row.envelope,
            )

    async def mark_published(self, row: PendingEvent) -> None:
        async with self.database.sessions() as db, db.begin():
            marked = await db.scalar(
                update(OutboxEvent)
                .where(
                    OutboxEvent.event_id == row.event_id,
                    OutboxEvent.published_at.is_(None),
                    OutboxEvent.aggregate_id == row.aggregate_id,
                    OutboxEvent.aggregate_version == row.version,
                    OutboxEvent.event_type == row.event_type,
                    OutboxEvent.occurred_at == row.occurred_at,
                    OutboxEvent.envelope == row.envelope,
                )
                .values(published_at=func.now())
                .returning(OutboxEvent.event_id)
            )
            if marked is None:
                raise InvalidEvent("Pending event changed before publication mark")

    async def backlog(self) -> tuple[int, float]:
        """Read durable pending state in one short query, outside publication transactions."""
        async with self.database.sessions() as db:
            count, age = (
                await db.execute(
                    select(
                        func.count(),
                        func.coalesce(
                            func.extract("epoch", func.now() - func.min(OutboxEvent.occurred_at)), 0
                        ),
                    ).where(OutboxEvent.published_at.is_(None))
                )
            ).one()
        return int(count), max(0.0, float(age))

    async def close(self) -> None:
        try:
            if self.guard_connection is not None:
                await self.guard_connection.close()
                self.guard_connection = None
        finally:
            await self.guard_engine.dispose()
            await self.database.close()
