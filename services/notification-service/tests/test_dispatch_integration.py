import asyncio
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from test_events import event
from test_inbox_integration import record, run_test

from notification_service.application.delivery import dispatch_once
from notification_service.domain.delivery import DeliveryResult, Recipient
from notification_service.infrastructure.dispatch import DispatchStore
from notification_service.infrastructure.models import DeliveryAttempt, ReadyDispatch

pytestmark = pytest.mark.integration


class User:
    state = "allowed"
    revision = 7
    during_lookup = None

    async def resolve(self, user_id):
        if self.during_lookup:
            await self.during_lookup()
        return Recipient(self.state, self.revision, 1234 if self.state == "allowed" else None)


class Bot:
    def __init__(self, *results):
        self.results = iter(results)
        self.calls = []

    async def send(self, chat_id, order_number):
        self.calls.append((chat_id, order_number))
        return next(self.results)


def ready(age=timedelta()):
    body = event()
    body["occurred_at"] = (datetime.now(UTC) - age).isoformat().replace("+00:00", "Z")
    return body


async def release_wait(inbox):
    async with inbox.engine.begin() as db:
        await db.execute(text("UPDATE ready_dispatches SET due_at = clock_timestamp()"))


async def evidence(inbox):
    async with inbox.sessions() as db:
        row = await db.scalar(select(ReadyDispatch))
        attempts = list(await db.scalars(select(DeliveryAttempt).order_by(DeliveryAttempt.number)))
        return row, attempts


def test_unknown_rechecks_then_sends_only_once():
    async def check(inbox):
        await inbox.ingest(record(ready()))
        store = DispatchStore(inbox.sessions)
        user = User()
        user.state = "unknown"
        bot = Bot(DeliveryResult("sent", message_id=42))
        await dispatch_once(store, user, bot)
        row, attempts = await evidence(inbox)
        assert row.state == "waiting" and not attempts and not bot.calls
        user.state = "allowed"
        await release_wait(inbox)
        await dispatch_once(store, user, bot)
        await dispatch_once(store, user, bot)
        row, attempts = await evidence(inbox)
        assert row.state == "sent"
        assert [(attempt.outcome, attempt.message_id) for attempt in attempts] == [("sent", 42)]
        assert bot.calls == [(1234, "MAI-000001")]

    run_test(check)


@pytest.mark.parametrize("freeze", [True, False])
def test_inbox_change_during_lookup_prevents_send(freeze):
    async def check(inbox):
        body = ready()
        await inbox.ingest(record(body))
        changed = deepcopy(body)
        if freeze:
            changed["payload"]["total_amount"] += 1
        else:
            changed["event_id"] = str(event()["event_id"])
            changed["payload"].update(status="COMPLETED", previous_status="READY", order_version=4)

        user = User()

        async def change_order():
            await inbox.ingest(record(changed, 1))

        user.during_lookup = change_order
        bot = Bot()
        await dispatch_once(DispatchStore(inbox.sessions), user, bot)
        row, attempts = await evidence(inbox)
        assert row.state == ("frozen" if freeze else "suppressed")
        assert not attempts and not bot.calls

    run_test(check)


def test_original_event_time_expires_even_when_newly_ingested():
    async def check(inbox):
        body = ready(timedelta(hours=25))
        await inbox.ingest(record(body))
        bot = Bot()
        await dispatch_once(DispatchStore(inbox.sessions), User(), bot)
        row, attempts = await evidence(inbox)
        assert row.state == "expired" and not attempts and not bot.calls

    run_test(check)


async def allow_claim_recovery(inbox):
    async with inbox.engine.begin() as db:
        await db.execute(text("UPDATE ready_dispatches SET lease_until = clock_timestamp()"))


def test_recovery_differentiates_lookup_from_possible_send_and_fences_stale_completion():
    async def check(inbox):
        await inbox.ingest(record(ready()))
        store = DispatchStore(inbox.sessions)
        user = User()
        recipient = await user.resolve(None)
        first, duplicate = await asyncio.gather(store.claim(), store.claim())
        lookup = first or duplicate
        assert bool(first) != bool(duplicate)
        await allow_claim_recovery(inbox)
        restarted = DispatchStore(inbox.sessions)
        await restarted.claim()
        row, attempts = await evidence(inbox)
        assert not row.possible_duplicate and not attempts

        crashed = await restarted.claim()
        assert not await store.authorize(lookup, recipient)
        assert await restarted.authorize(crashed, recipient)
        await allow_claim_recovery(inbox)
        await store.claim()
        row, attempts = await evidence(inbox)
        assert row.possible_duplicate and attempts[0].outcome == "uncertain"

        await release_wait(inbox)
        retry = await store.claim()
        assert await store.authorize(retry, recipient)
        await restarted.complete(crashed, recipient, DeliveryResult("sent", message_id=5))
        await store.complete(retry, recipient, DeliveryResult("sent", message_id=6))
        row, attempts = await evidence(inbox)
        assert row.state == "sent" and row.possible_duplicate
        assert [(a.outcome, a.message_id) for a in attempts] == [("uncertain", None), ("sent", 6)]

    run_test(check)


def test_uncertain_retries_stop_at_eight():
    async def check(inbox):
        await inbox.ingest(record(ready()))
        bot = Bot(*[DeliveryResult("uncertain")] * 8)
        for _ in range(9):
            await release_wait(inbox)
            await dispatch_once(DispatchStore(inbox.sessions), User(), bot)
        row, attempts = await evidence(inbox)
        assert row.state == "exhausted" and row.possible_duplicate
        assert len(bot.calls) == len(attempts) == 8
        assert all(a.outcome == "uncertain" and a.message_id is None for a in attempts)

    run_test(check)


def test_long_rate_limit_expires_first_order_and_delays_others_across_restart():
    async def check(inbox):
        await inbox.ingest(record(ready()))
        bot = Bot(DeliveryResult("rate_limited", retry_after=25 * 3600))
        await dispatch_once(DispatchStore(inbox.sessions), User(), bot)
        row, attempts = await evidence(inbox)
        assert row.state == "expired" and attempts[0].retry_after == 25 * 3600
        await inbox.ingest(record(ready(), 1))
        for _ in range(2):
            await dispatch_once(DispatchStore(inbox.sessions), User(), bot)
        assert len(bot.calls) == 1
        async with inbox.engine.begin() as db:
            await db.execute(text("UPDATE dispatch_bot SET cooldown_until = NULL"))
        new_bot = Bot(DeliveryResult("sent", message_id=101))
        await dispatch_once(DispatchStore(inbox.sessions), User(), new_bot)
        assert len(new_bot.calls) == 1

    run_test(check)


def test_block_is_durable_and_revision_conflict_never_replays_stale_report():
    async def check(inbox):
        await inbox.ingest(record(ready()))
        user = User()
        user.reports = []

        async def report(observation):
            user.reports.append(observation)
            return "retry" if len(user.reports) == 1 else "revision_conflict"

        user.report = report
        bot = Bot(DeliveryResult("blocked"))
        for _ in range(4):
            async with inbox.engine.begin() as db:
                await db.execute(
                    text(
                        "UPDATE ready_dispatches SET report_due_at = clock_timestamp() "
                        "WHERE report_due_at IS NOT NULL"
                    )
                )
            await dispatch_once(DispatchStore(inbox.sessions), user, bot)
            user.revision = 9
        row, attempts = await evidence(inbox)
        assert row.state == "blocked" and row.report_state == "stale"
        assert row.report_chat_id is None and len(bot.calls) == len(attempts) == 1
        assert len(user.reports) == 2
        for report in user.reports:
            assert report.notification_id == row.notification_id
            assert report.revision == 7 and report.chat_id == 1234

    run_test(check)


@pytest.mark.parametrize("outcome,state", [("bad_request", "failed"), ("paused", "waiting")])
def test_malformed_request_and_bot_pause_are_distinct(outcome, state):
    async def check(inbox):
        await inbox.ingest(record(ready()))
        bot = Bot(DeliveryResult(outcome))
        await dispatch_once(DispatchStore(inbox.sessions), User(), bot)
        row, attempts = await evidence(inbox)
        assert row.state == state and row.report_state is None and len(attempts) == 1
        async with inbox.engine.begin() as db:
            assert await db.scalar(text("SELECT paused FROM dispatch_bot")) == (outcome == "paused")

    run_test(check)


def test_observed_user_block_suppresses_current_obligation_permanently():
    async def check(inbox):
        await inbox.ingest(record(ready()))
        user, bot = User(), Bot()
        user.state = "blocked"
        await dispatch_once(DispatchStore(inbox.sessions), user, bot)
        user.state, user.revision = "allowed", 8
        await release_wait(inbox)
        await dispatch_once(DispatchStore(inbox.sessions), user, bot)
        row, attempts = await evidence(inbox)
        assert row.state == "blocked" and row.detail == "user_blocked"
        assert row.report_state is None and not attempts and not bot.calls

    run_test(check)


def test_definitive_block_gates_other_orders_until_user_revision_advances():
    async def check(inbox):
        first = ready()
        await inbox.ingest(record(first))
        user = User()

        async def report(observation):
            return "retry"

        user.report = report
        bot = Bot(DeliveryResult("blocked"), *[DeliveryResult("sent", message_id=10)] * 2)
        store = DispatchStore(inbox.sessions)
        await dispatch_once(store, user, bot)

        for offset in (1, 2):
            work = ready()
            work["payload"]["user_id"] = first["payload"]["user_id"]
            await inbox.ingest(record(work, offset))
            if offset == 2:
                user.revision = 8
            await dispatch_once(store, user, bot)
        async with inbox.sessions() as db:
            states = list(
                await db.scalars(select(ReadyDispatch.state).order_by(ReadyDispatch.state))
            )
        assert states == ["blocked", "blocked", "sent"]
        assert len(bot.calls) == 2

    run_test(check)
