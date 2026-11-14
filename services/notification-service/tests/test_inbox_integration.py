import asyncio
import json
import os
from copy import deepcopy
from uuid import uuid4

import asyncpg
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from test_events import event

from notification_service.infrastructure.inbox import InboxStore, Record, RecoveryRequired
from notification_service.infrastructure.models import Inbox, Obligation, OrderObservation, Receipt

pytestmark = pytest.mark.integration


def run_test(test, group_id="test-group"):
    url = os.environ.get("MAI_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Use the isolated integration runner")

    async def run():
        store = InboxStore(url, group_id, 2)
        try:
            async with store.engine.begin() as db:
                await db.execute(
                    text(
                        "TRUNCATE source_receipts, notification_inbox, ready_obligations, "
                        "observed_versions, order_observations, source_checkpoints CASCADE"
                    )
                )
                await db.execute(
                    text("UPDATE dispatch_bot SET paused = false, cooldown_until = NULL")
                )
            await store.initialize("test-topic", 0, 0, 100, None)
            await test(store)
        finally:
            await store.close()

    asyncio.run(run())


def record(body, offset=0):
    return Record("test-topic", 0, offset, body["aggregate_id"].encode(), json.dumps(body).encode())


async def count(store, model):
    async with store.sessions() as db:
        return await db.scalar(select(func.count()).select_from(model))


def test_duplicate_id_and_equivalent_version_create_one_obligation():
    async def check(store):
        body = event()
        assert await store.ingest(record(body)) == "ACCEPTED"
        assert await store.ingest(record(body)) == "REPLAY"
        assert await store.ingest(record(body, 1)) == "DUPLICATE_ID"
        equivalent = deepcopy(body)
        equivalent["event_id"] = str(uuid4())
        assert await store.ingest(record(equivalent, 2)) == "DUPLICATE_VERSION"
        assert await count(store, Inbox) == 2 and await count(store, Obligation) == 1
        assert await count(store, Receipt) == 3

    run_test(check)


@pytest.mark.parametrize("same_id", [True, False])
def test_conflicts_freeze_pending_work(same_id):
    async def check(store):
        body = event()
        await store.ingest(record(body))
        conflict = deepcopy(body)
        conflict["payload"]["total_amount"] += 1
        if not same_id:
            conflict["event_id"] = str(uuid4())
        assert await store.ingest(record(conflict, 1)) == "QUARANTINED"
        async with store.sessions() as db:
            assert (await db.scalar(select(OrderObservation))).frozen
            assert (await db.scalar(select(Obligation))).state == "FROZEN"

    run_test(check)


def test_terminal_before_ready_suppresses_without_regression():
    async def check(store):
        terminal = event("COMPLETED", 4)
        ready = deepcopy(terminal)
        ready["event_id"] = str(uuid4())
        ready["payload"].update(status="READY", previous_status="PREPARING", order_version=3)
        await store.ingest(record(terminal))
        await store.ingest(record(ready, 1))
        assert await count(store, Obligation) == 0
        async with store.sessions() as db:
            observation = await db.scalar(select(OrderObservation))
            assert observation.version == 4 and observation.status == "COMPLETED"

    run_test(check)


def test_ready_then_terminal_suppresses_and_branch_fork_freezes():
    async def check(store):
        ready = event()
        await store.ingest(record(ready))
        terminal = deepcopy(ready)
        terminal["event_id"] = str(uuid4())
        terminal["payload"].update(status="COMPLETED", previous_status="READY", order_version=4)
        await store.ingest(record(terminal, 1))
        async with store.sessions() as db:
            assert (await db.scalar(select(Obligation))).state == "SUPPRESSED"
        cancelled = deepcopy(ready)
        cancelled["event_id"] = str(uuid4())
        cancelled["event_type"] = "ORDER_CANCELLED"
        cancelled["payload"].update(
            status="CANCELLED", previous_status="PREPARING", order_version=5
        )
        assert await store.ingest(record(cancelled, 2)) == "QUARANTINED"

    run_test(check)


def test_poison_is_durable_and_database_failure_does_not_advance():
    async def check(store):
        assert await store.ingest(Record("test-topic", 0, 0, None, b"not-json")) == "QUARANTINED"
        async with store.engine.begin() as db:
            await db.execute(
                text(
                    "ALTER TABLE source_receipts ADD CONSTRAINT reject_receipt "
                    "CHECK (false) NOT VALID"
                )
            )
        try:
            with pytest.raises(IntegrityError):
                await store.ingest(record(event(), 1))
            assert await store.position("test-topic", 0) == 1
            assert await count(store, Inbox) == 0
        finally:
            async with store.engine.begin() as db:
                await db.execute(text("ALTER TABLE source_receipts DROP CONSTRAINT reject_receipt"))
        await store.ingest(record(event(), 1))
        assert await store.position("test-topic", 0) == 2

    run_test(check)


def test_version_overflow_is_quarantined_without_blocking_next_record():
    async def check(store):
        assert await store.ingest(record(event(version=2**31))) == "QUARANTINED"
        assert await store.ingest(record(event(), 1)) == "ACCEPTED"
        assert await store.position("test-topic", 0) == 2
        assert await count(store, Obligation) == 1
        async with store.sessions() as db:
            receipt = await db.scalar(select(Receipt).where(Receipt.offset == 0))
            assert receipt.reason == "version_bounds" and receipt.protected_value is not None

    run_test(check)


def test_restore_ahead_behind_and_retention_gap_fail_closed():
    async def check(store):
        await store.ingest(record(event()))
        assert await store.initialize("test-topic", 0, 0, 100, 0) == 0
        assert await store.initialize("test-topic", 0, 0, 100, None) == 0
        with pytest.raises(RecoveryRequired):
            await store.initialize("test-topic", 0, 0, 100, 2)
        with pytest.raises(RecoveryRequired):
            await store.initialize("test-topic", 0, 2, 100, 1)
        with pytest.raises(RecoveryRequired):
            await store.initialize("missing", 0, 0, 100, 5)

    run_test(check)


def test_concurrent_versions_and_source_reuse_are_safe():
    async def check(store):
        body = event()
        await asyncio.gather(store.ingest(record(body)), store.ingest(record(body)))
        assert await count(store, Obligation) == 1
        changed = event()
        with pytest.raises(RecoveryRequired):
            await store.ingest(record(changed))
        assert await count(store, Inbox) == 1

    run_test(check)


def test_concurrent_partitions_never_regress_terminal_state():
    async def check(store):
        await store.initialize("test-topic", 1, 0, 100, None)
        ready = event()
        terminal = deepcopy(ready)
        terminal["event_id"] = str(uuid4())
        terminal["payload"].update(status="COMPLETED", previous_status="READY", order_version=4)
        second = record(terminal)
        await asyncio.gather(
            store.ingest(record(ready)),
            store.ingest(Record(second.topic, 1, 0, second.key, second.value)),
        )
        async with store.sessions() as db:
            observation = await db.scalar(select(OrderObservation))
            assert observation.version == 4 and observation.status == "COMPLETED"
            assert observation.gap_observed and not observation.frozen
            assert all(row.state == "SUPPRESSED" for row in await db.scalars(select(Obligation)))

    run_test(check)


def test_same_event_id_redirected_to_another_order_freezes_both():
    async def check(store):
        original = event()
        await store.ingest(record(original))
        changed = deepcopy(original)
        changed["aggregate_id"] = str(uuid4())
        assert await store.ingest(record(changed, 1)) == "QUARANTINED"
        async with store.sessions() as db:
            observations = list(await db.scalars(select(OrderObservation)))
            assert len(observations) == 2 and all(row.frozen for row in observations)

    run_test(check)


def test_notification_role_has_no_other_service_database_access():
    async def check(store):
        async with store.engine.connect() as db:
            role = (
                await db.execute(
                    text(
                        "SELECT current_user, rolsuper, rolcreatedb, rolcreaterole, "
                        "rolreplication, rolbypassrls FROM pg_roles WHERE rolname=current_user"
                    )
                )
            ).one()
            assert role[0] == "notifications_owner" and all(flag is False for flag in role[1:])
        for database in ("users_db", "menu_db", "orders_db"):
            engine = create_async_engine(store.engine.url.set(database=database))
            try:
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    async with engine.connect():
                        pass
            finally:
                await engine.dispose()

    run_test(check)
