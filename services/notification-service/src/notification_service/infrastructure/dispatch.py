from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import false, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from notification_service.domain.delivery import (
    CLAIM_LEASE,
    MAX_ATTEMPTS,
    READY_WINDOW,
    BlockReport,
    Claim,
    DeliveryResult,
    Recipient,
    ReportResult,
    retry_delay,
)
from notification_service.infrastructure.models import (
    DeliveryAttempt,
    DispatchBot,
    Inbox,
    Obligation,
    OrderObservation,
    ReadyDispatch,
)


def release(row: ReadyDispatch) -> None:
    row.claim_token = row.lease_until = None


def reschedule(row: ReadyDispatch, when: datetime) -> None:
    if row.attempt_count >= MAX_ATTEMPTS:
        row.state = "exhausted"
    elif when >= row.expires_at:
        row.state = "expired"
    else:
        row.state, row.due_at = "waiting", when
    release(row)


def stop_if_ineligible(
    row: ReadyDispatch, order: OrderObservation, obligation: Obligation, now: datetime
) -> bool:
    if order.frozen or obligation.state == "FROZEN":
        row.state = "frozen"
    elif obligation.state != "PENDING" or (order.status, order.version) != (
        "READY",
        row.version,
    ):
        row.state = "suppressed"
    elif now >= row.expires_at:
        row.state = "expired"
    else:
        return False
    release(row)
    return True


class DispatchStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[tuple[AsyncSession, DispatchBot]]:
        # Every dispatcher takes this lock before the inbox's order -> obligation lock order.
        async with self.sessions() as db, db.begin():
            await db.execute(text("SET LOCAL lock_timeout='2000ms'"))
            await db.execute(text("SET LOCAL statement_timeout='5000ms'"))
            bot = await db.get(DispatchBot, 1, with_for_update=True)
            if bot is None:
                raise RuntimeError("dispatch_bot_missing")
            yield db, bot

    async def lock_order(
        self, db: AsyncSession, order_id: UUID, version: int
    ) -> tuple[OrderObservation, Obligation, ReadyDispatch | None]:
        order = await db.get(OrderObservation, order_id, with_for_update=True)
        obligation = await db.get(Obligation, (order_id, version), with_for_update=True)
        if order is None or obligation is None:
            raise RuntimeError("dispatch_obligation_missing")
        row = await db.get(ReadyDispatch, (order_id, version), with_for_update=True)
        return order, obligation, row

    async def claim(self) -> Claim | None:
        async with self.transaction() as (db, bot):
            now = await db_time(db)
            active = (
                await db.execute(
                    select(
                        ReadyDispatch.order_id, ReadyDispatch.version, ReadyDispatch.lease_until
                    ).where(ReadyDispatch.claim_token.is_not(None))
                )
            ).one_or_none()
            if active:
                if active.lease_until > now:
                    return None
                order, obligation, row = await self.lock_order(db, active.order_id, active.version)
                assert row is not None
                if row.state == "sending":
                    attempt = await self.open_attempt(db, row)
                    attempt.outcome, attempt.finished_at = "uncertain", now
                    row.possible_duplicate = True
                    row.detail = "lease_expired"
                    reschedule(row, now + retry_delay(row.attempt_count))
                release(row)
                if row.state == "waiting":
                    stop_if_ineligible(row, order, obligation, now)
                return None

            may_send = not bot.paused and (bot.cooldown_until is None or bot.cooldown_until <= now)
            key = (
                await db.execute(
                    select(Obligation.order_id, Obligation.version)
                    .outerjoin(ReadyDispatch)
                    .where(
                        or_(
                            ReadyDispatch.order_id.is_(None),
                            (ReadyDispatch.state == "waiting")
                            & or_(
                                Obligation.state != "PENDING",
                                ReadyDispatch.expires_at <= now,
                                (ReadyDispatch.due_at <= now) if may_send else false(),
                            ),
                        )
                    )
                    .order_by(ReadyDispatch.due_at.nulls_last(), Obligation.created_at)
                    .limit(1)
                )
            ).one_or_none()
            if key is None:
                return None

            order, obligation, row = await self.lock_order(db, key.order_id, key.version)
            now = await db_time(db)
            source = await db.get(Inbox, obligation.event_id)
            if source is None:
                raise RuntimeError("dispatch_event_missing")
            if row is None:
                occurred = datetime.fromisoformat(source.envelope["occurred_at"])
                row = ReadyDispatch(
                    order_id=key.order_id,
                    version=key.version,
                    notification_id=uuid4(),
                    expires_at=min(occurred, datetime.max.replace(tzinfo=UTC) - READY_WINDOW)
                    + READY_WINDOW,
                    due_at=occurred,
                    state="waiting",
                    attempt_count=0,
                    possible_duplicate=False,
                    report_tries=0,
                )
                db.add(row)
            if stop_if_ineligible(row, order, obligation, now) or not may_send or row.due_at > now:
                return None
            token = uuid4()
            row.claim_token, row.lease_until = token, now + CLAIM_LEASE
            return Claim(
                key.order_id,
                key.version,
                token,
                obligation.user_id,
                source.envelope["payload"]["order_number"],
            )

    async def authorize(self, claim: Claim, recipient: Recipient) -> bool:
        async with self.transaction() as (db, _):
            order, obligation, row = await self.lock_order(db, claim.order_id, claim.version)
            now = await db_time(db)
            if not owns(row, claim, now, "waiting"):
                return False
            assert row is not None
            if stop_if_ineligible(row, order, obligation, now):
                return False
            if recipient.state == "blocked":
                row.state, row.detail = "blocked", "user_blocked"
                release(row)
                return False
            if recipient.state != "allowed" or recipient.chat_id is None:
                row.detail = recipient.state
                row.due_at = min(now + timedelta(seconds=30), row.expires_at)
                release(row)
                return False
            # User may still show the old grant while a durable block report is pending.
            prior_block = await db.scalar(
                select(ReadyDispatch.block_revision)
                .join(Obligation)
                .where(
                    Obligation.user_id == claim.user_id,
                    ReadyDispatch.block_revision >= recipient.revision,
                )
                .limit(1)
            )
            if prior_block is not None:
                row.state, row.detail = "blocked", "local_block"
                release(row)
                return False
            row.attempt_count += 1
            row.state, row.detail = "sending", None
            row.lease_until = now + CLAIM_LEASE
            db.add(
                DeliveryAttempt(
                    order_id=row.order_id,
                    version=row.version,
                    number=row.attempt_count,
                    started_at=now,
                    outcome="in_flight",
                )
            )
            return True

    async def complete(self, claim: Claim, recipient: Recipient, result: DeliveryResult) -> None:
        async with self.transaction() as (db, bot):
            order, obligation, row = await self.lock_order(db, claim.order_id, claim.version)
            now = await db_time(db)
            if not owns(row, claim, now, "sending"):
                return
            assert row is not None
            attempt = await self.open_attempt(db, row)
            attempt.finished_at, attempt.outcome = now, result.outcome
            attempt.message_id, attempt.retry_after = result.message_id, result.retry_after
            row.detail = result.outcome
            due = now + retry_delay(row.attempt_count)
            if result.outcome == "uncertain":
                row.possible_duplicate = True
            if result.outcome == "rate_limited" and result.retry_after is not None:
                until = now + timedelta(seconds=result.retry_after)
                bot.cooldown_until = max(bot.cooldown_until or until, until)
                due = max(due, until)
            if result.outcome == "paused":
                bot.paused = True
            release(row)
            if result.outcome == "sent":
                row.state = "sent"
            elif result.outcome == "blocked":
                row.state = "blocked"
                row.block_revision, row.report_chat_id = recipient.revision, recipient.chat_id
                row.report_state, row.report_due_at = "pending", now
            elif result.outcome == "bad_request":
                row.state = "failed"
            elif not stop_if_ineligible(row, order, obligation, now):
                reschedule(row, due)

    @staticmethod
    async def open_attempt(db: AsyncSession, row: ReadyDispatch) -> DeliveryAttempt:
        attempt = await db.get(DeliveryAttempt, (row.order_id, row.version, row.attempt_count))
        if attempt is None or attempt.outcome != "in_flight":
            raise RuntimeError("dispatch_attempt_missing")
        return attempt

    async def due_report(self) -> BlockReport | None:
        async with self.transaction() as (db, _):
            result = (
                await db.execute(
                    select(ReadyDispatch, Obligation.user_id)
                    .join(Obligation)
                    .where(ReadyDispatch.report_due_at <= func.clock_timestamp())
                    .order_by(ReadyDispatch.report_due_at)
                    .limit(1)
                )
            ).one_or_none()
            if result is None:
                return None
            row, user_id = result
            assert row.block_revision is not None and row.report_state is not None
            return BlockReport(
                user_id,
                row.notification_id,
                row.block_revision,
                row.report_chat_id,
                row.report_state,
                row.report_tries,
            )

    async def complete_report(self, report: BlockReport, result: ReportResult) -> None:
        async with self.transaction() as (db, _):
            row = await db.scalar(
                select(ReadyDispatch).where(ReadyDispatch.notification_id == report.notification_id)
            )
            if row is None or (row.report_state, row.report_tries) != (report.state, report.tries):
                return
            row.report_tries += 1
            if result == "retry":
                row.report_due_at = await db_time(db) + retry_delay(row.report_tries)
            elif result == "revision_conflict":
                row.report_chat_id = None
                row.report_state, row.report_due_at = "refresh", await db_time(db)
            else:
                row.report_state, row.report_due_at, row.report_chat_id = result, None, None


async def db_time(db: AsyncSession) -> datetime:
    now = await db.scalar(select(func.clock_timestamp()))
    assert isinstance(now, datetime)
    return now


def owns(row: ReadyDispatch | None, claim: Claim, now: datetime, state: str) -> bool:
    return (
        row is not None
        and row.state == state
        and row.claim_token == claim.token
        and row.lease_until is not None
        and row.lease_until > now
    )
