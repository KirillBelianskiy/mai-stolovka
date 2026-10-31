import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import asyncpg
import pytest
from conftest import auth
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker

from order_service.config import Settings
from order_service.domain.orders import DishSnapshot

pytestmark = pytest.mark.integration
EVENT_SCHEMA = json.loads(
    (
        Path(__file__).resolve().parents[3] / "packages/contracts/events/envelope-v1.schema.json"
    ).read_text()
)
EVENT_VALIDATOR = Draft202012Validator(EVENT_SCHEMA, format_checker=FormatChecker())


def db_query(settings: Settings, sql: str, *args: object) -> list[dict[str, object]]:
    async def execute() -> list[dict[str, object]]:
        connection = await asyncpg.connect(
            settings.database_url.get_secret_value().replace(
                "postgresql+asyncpg://", "postgresql://"
            )
        )
        try:
            return [dict(row) for row in await connection.fetch(sql, *args)]
        finally:
            await connection.close()

    return asyncio.run(execute())


def prepare(
    client: TestClient, private: bytes, capacity: int = 5
) -> tuple[dict[str, str], dict[str, object], str]:
    admin = auth(private, "ADMIN")
    start = datetime.now(UTC) + timedelta(hours=1)
    slot = client.post(
        "/slots",
        headers=admin,
        json={
            "start_time": start.isoformat(),
            "end_time": (start + timedelta(minutes=10)).isoformat(),
            "capacity": capacity,
        },
    )
    assert slot.status_code == 201, slot.text
    dish_id = uuid4()
    client.app.state.menu.dishes[dish_id] = DishSnapshot(dish_id, "Суп", 12000)
    body = {
        "slot_id": slot.json()["id"],
        "items": [{"menu_item_id": str(dish_id), "quantity": 2}],
        "expected_total_amount": 24000,
    }
    return admin, body, slot.json()["id"]


def submit(
    client: TestClient, body: dict[str, object], headers: dict[str, str], key: UUID | None = None
):
    return client.post("/", headers={**headers, "Idempotency-Key": str(key or uuid4())}, json=body)


def counts(settings: Settings) -> dict[str, object]:
    for row in db_query(settings, "SELECT envelope FROM outbox_events"):
        envelope = row["envelope"]
        EVENT_VALIDATOR.validate(json.loads(envelope) if isinstance(envelope, str) else envelope)
    return db_query(
        settings,
        "SELECT (SELECT count(*) FROM orders) AS orders, "
        "(SELECT count(*) FROM order_items) AS items, "
        "(SELECT count(*) FROM idempotency_records) AS keys, "
        "(SELECT count(*) FROM outbox_events) AS events, "
        "(SELECT coalesce(sum(current_orders),0) FROM time_slots) AS reservations",
    )[0]


def test_create_replay_without_menu_and_immutable_history(
    integration_client, integration_settings, auth_keys
):
    client = integration_client
    admin, body, slot_id = prepare(client, auth_keys[0])
    owner = auth(auth_keys[0])
    key = uuid4()
    created = submit(client, body, owner, key)
    assert created.status_code == 201, created.text
    original = created.json()
    item = original["items"][0]
    assert original["total_amount"] == 24000 and item["name_at_moment"] == "Суп"
    assert original["version"] == 1 and original["order_number"].startswith("MAI-")
    dish_id = UUID(item["menu_item_id"])
    client.app.state.menu.dishes[dish_id] = DishSnapshot(dish_id, "Changed", 99999)
    client.app.state.menu.failed = True
    replay = submit(client, body, owner, key)
    assert replay.status_code == 201 and replay.json() == original
    assert replay.headers["idempotency-replayed"] == "true"
    assert client.app.state.menu.calls == 1
    assert client.get(f"/{original['id']}", headers=owner).json()["items"][0] == item
    assert counts(integration_settings) == {
        "orders": 1,
        "items": 1,
        "keys": 1,
        "events": 1,
        "reservations": 1,
    }
    event = db_query(
        integration_settings,
        "SELECT event_type, aggregate_version, published_at, envelope FROM outbox_events",
    )[0]
    assert event["event_type"] == "ORDER_CREATED" and event["aggregate_version"] == 1
    assert event["published_at"] is None
    conflict = submit(client, {**body, "expected_total_amount": 1}, owner, key)
    assert (
        conflict.status_code == 409 and conflict.json()["detail"]["code"] == "IDEMPOTENCY_CONFLICT"
    )


def test_concurrent_capacity_never_overbooks(integration_client, integration_settings, auth_keys):
    client = integration_client
    _, body, _ = prepare(client, auth_keys[0], capacity=3)
    headers = auth(auth_keys[0])
    with ThreadPoolExecutor(max_workers=10) as pool:
        responses = list(pool.map(lambda _: submit(client, body, headers), range(10)))
    assert sum(r.status_code == 201 for r in responses) == 3, [r.status_code for r in responses]
    assert all(r.status_code in {201, 409} for r in responses)
    assert (
        counts(integration_settings)["reservations"] == counts(integration_settings)["orders"] == 3
    )
    assert counts(integration_settings)["keys"] == counts(integration_settings)["events"] == 3


def test_concurrent_duplicate_is_one_order(integration_client, integration_settings, auth_keys):
    client = integration_client
    _, body, _ = prepare(client, auth_keys[0], capacity=1)
    headers = auth(auth_keys[0])
    key = uuid4()
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: submit(client, body, headers, key), range(8)))
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1
    assert counts(integration_settings) == {
        "orders": 1,
        "items": 1,
        "keys": 1,
        "events": 1,
        "reservations": 1,
    }


def test_price_confirmation_and_menu_failure_leave_no_reservation(
    integration_client, integration_settings, auth_keys
):
    client = integration_client
    _, body, _ = prepare(client, auth_keys[0])
    owner = auth(auth_keys[0])
    key = uuid4()
    changed = submit(client, {**body, "expected_total_amount": 1}, owner, key)
    assert changed.status_code == 409 and changed.json()["detail"]["total_amount"] == 24000
    assert all(value == 0 for value in counts(integration_settings).values())
    client.app.state.menu.failed = True
    assert submit(client, body, owner, key).status_code == 503
    assert all(value == 0 for value in counts(integration_settings).values())
    client.app.state.menu.failed = False
    assert submit(client, body, owner, key).status_code == 201


def test_outbox_failure_rolls_back_every_write(integration_client, integration_settings, auth_keys):
    client = integration_client
    _, body, _ = prepare(client, auth_keys[0])
    db_query(
        integration_settings,
        "ALTER TABLE outbox_events ADD CONSTRAINT test_reject_outbox CHECK (false) NOT VALID",
    )
    try:
        assert submit(client, body, auth(auth_keys[0])).status_code == 503
        assert counts(integration_settings) == {
            "orders": 0,
            "items": 0,
            "keys": 0,
            "events": 0,
            "reservations": 0,
        }
    finally:
        db_query(
            integration_settings, "ALTER TABLE outbox_events DROP CONSTRAINT test_reject_outbox"
        )


def test_network_lookup_runs_before_any_slot_lock(
    integration_client, integration_settings, auth_keys
):
    client = integration_client
    _, body, slot_id = prepare(client, auth_keys[0])
    original = client.app.state.menu.snapshot

    async def check_snapshot(ids):
        connection = await asyncpg.connect(
            integration_settings.database_url.get_secret_value().replace(
                "postgresql+asyncpg://", "postgresql://"
            )
        )
        try:
            async with connection.transaction():
                await connection.execute(
                    "SELECT id FROM time_slots WHERE id=$1 FOR UPDATE NOWAIT", UUID(slot_id)
                )
                assert await connection.fetchval("SELECT count(*) FROM idempotency_records") == 0
        finally:
            await connection.close()
        return await original(ids)

    client.app.state.menu.snapshot = check_snapshot
    assert submit(client, body, auth(auth_keys[0])).status_code == 201


def test_status_roles_versions_and_terminal_state(
    integration_client, integration_settings, auth_keys
):
    client = integration_client
    _, body, _ = prepare(client, auth_keys[0])
    owner = auth(auth_keys[0])
    value = submit(client, body, owner).json()
    order_id = value["id"]
    cook, cashier = auth(auth_keys[0], "COOK"), auth(auth_keys[0], "CASHIER")
    assert (
        client.patch(
            f"/{order_id}/status",
            headers=owner,
            json={"status": "PREPARING", "expected_version": 1},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/{order_id}/status",
            headers=cashier,
            json={"status": "PREPARING", "expected_version": 1},
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/{order_id}/status",
            headers=cook,
            json={"status": "READY", "expected_version": 1},
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"/{order_id}/status",
            headers=cook,
            json={"status": "PREPARING", "expected_version": 1},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/{order_id}/status",
            headers=cook,
            json={"status": "PREPARING", "expected_version": 1},
        ).status_code
        == 409
    )
    assert (
        client.patch(
            f"/{order_id}/status",
            headers=cook,
            json={"status": "READY", "expected_version": 2},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/{order_id}/status",
            headers=cook,
            json={"status": "COMPLETED", "expected_version": 3},
        ).status_code
        == 403
    )
    final = client.patch(
        f"/{order_id}/status",
        headers=cashier,
        json={"status": "COMPLETED", "expected_version": 3},
    )
    assert final.status_code == 200 and final.json()["version"] == 4
    assert (
        client.post(f"/{order_id}/cancel", headers=owner, json={"expected_version": 4}).status_code
        == 409
    )
    assert (
        counts(integration_settings)["events"] == 4
        and counts(integration_settings)["reservations"] == 1
    )


def test_client_ownership_and_idempotency_key_scope(
    integration_client, integration_settings, auth_keys
):
    client = integration_client
    admin, body, _ = prepare(client, auth_keys[0])
    owner = auth(auth_keys[0])
    other = auth(auth_keys[0])
    key = uuid4()
    first = submit(client, body, owner, key).json()
    assert client.get(f"/{first['id']}", headers=other).status_code == 404
    assert client.get("/", headers=other).json()["total"] == 0
    assert (
        client.post(
            f"/{first['id']}/cancel", headers=other, json={"expected_version": 1}
        ).status_code
        == 404
    )
    assert submit(client, body, other, key).status_code == 201
    assert client.get("/", headers=owner).json()["total"] == 1
    assert client.get("/", headers=admin).json()["total"] == 2
    assert submit(client, body, admin).status_code == 403


def test_repeated_and_concurrent_cancellation_frees_once(
    integration_client, integration_settings, auth_keys
):
    client = integration_client
    _, body, _ = prepare(client, auth_keys[0])
    owner = auth(auth_keys[0])
    value = submit(client, body, owner).json()
    order_id = value["id"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(
            pool.map(
                lambda _: client.post(
                    f"/{order_id}/cancel", headers=owner, json={"expected_version": 1}
                ),
                range(8),
            )
        )
    assert all(r.status_code == 200 and r.json()["status"] == "CANCELLED" for r in responses)
    assert counts(integration_settings)["reservations"] == 0
    assert counts(integration_settings)["events"] == 2


def test_distinct_order_cancellations_share_capacity_safely(
    integration_client, integration_settings, auth_keys
):
    client = integration_client
    _, body, _ = prepare(client, auth_keys[0], capacity=6)
    owner = auth(auth_keys[0])
    ids = [submit(client, body, owner).json()["id"] for _ in range(6)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        responses = list(
            pool.map(
                lambda i: client.post(f"/{i}/cancel", headers=owner, json={"expected_version": 1}),
                ids,
            )
        )
    assert all(r.status_code == 200 for r in responses)
    assert counts(integration_settings)["reservations"] == 0
    assert counts(integration_settings)["events"] == 12


def test_admin_can_cancel_preparing_but_owner_cannot(
    integration_client, integration_settings, auth_keys
):
    client = integration_client
    admin, body, _ = prepare(client, auth_keys[0])
    owner = auth(auth_keys[0])
    cook = auth(auth_keys[0], "COOK")
    order_id = submit(client, body, owner).json()["id"]
    assert (
        client.patch(
            f"/{order_id}/status",
            headers=cook,
            json={"status": "PREPARING", "expected_version": 1},
        ).status_code
        == 200
    )
    assert (
        client.post(f"/{order_id}/cancel", headers=owner, json={"expected_version": 2}).status_code
        == 409
    )
    assert (
        client.post(f"/{order_id}/cancel", headers=cook, json={"expected_version": 2}).status_code
        == 403
    )
    assert (
        client.post(f"/{order_id}/cancel", headers=admin, json={"expected_version": 2}).status_code
        == 200
    )
    assert counts(integration_settings)["reservations"] == 0


def test_concurrent_status_update_commits_once(integration_client, integration_settings, auth_keys):
    client = integration_client
    _, body, _ = prepare(client, auth_keys[0])
    owner = auth(auth_keys[0])
    cook = auth(auth_keys[0], "COOK")
    order_id = submit(client, body, owner).json()["id"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(
            pool.map(
                lambda _: client.patch(
                    f"/{order_id}/status",
                    headers=cook,
                    json={"status": "PREPARING", "expected_version": 1},
                ),
                range(8),
            )
        )
    assert sum(r.status_code == 200 for r in responses) == 1
    assert all(r.status_code in {200, 409} for r in responses)
    assert counts(integration_settings)["events"] == 2


def test_booking_and_cancellation_close_at_start(
    integration_client, integration_settings, auth_keys
):
    client = integration_client
    _, body, slot_id = prepare(client, auth_keys[0])
    owner = auth(auth_keys[0])
    order_id = submit(client, body, owner).json()["id"]
    db_query(
        integration_settings,
        "UPDATE time_slots SET start_time=now()-interval '1 minute' WHERE id=$1",
        UUID(slot_id),
    )
    assert submit(client, body, owner).status_code == 409
    assert (
        client.post(f"/{order_id}/cancel", headers=owner, json={"expected_version": 1}).status_code
        == 409
    )
    assert counts(integration_settings)["reservations"] == 1


def test_slot_management_preserves_capacity_and_history(
    integration_client, integration_settings, auth_keys
):
    client = integration_client
    admin, body, slot_id = prepare(client, auth_keys[0], capacity=2)
    owner = auth(auth_keys[0])
    slot = client.get("/slots", headers=owner).json()[0]
    assert slot["remaining_capacity"] == 2
    assert client.post("/slots", headers=owner, json={}).status_code == 403
    submit(client, body, owner)
    submit(client, body, owner)
    update = {"start_time": slot["start_time"], "end_time": slot["end_time"], "capacity": 1}
    assert client.put(f"/slots/{slot_id}", headers=admin, json=update).status_code == 409
    update["capacity"] = 3
    assert client.put(f"/slots/{slot_id}", headers=admin, json=update).status_code == 200
    update["start_time"] = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    update["end_time"] = (datetime.now(UTC) + timedelta(hours=3)).isoformat()
    assert client.put(f"/slots/{slot_id}", headers=admin, json=update).status_code == 409
    assert client.delete(f"/slots/{slot_id}", headers=admin).status_code == 409


def test_database_capacity_constraint(integration_client, integration_settings, auth_keys):
    _, _, slot_id = prepare(integration_client, auth_keys[0])
    with pytest.raises(asyncpg.CheckViolationError):
        db_query(
            integration_settings,
            "UPDATE time_slots SET current_orders=capacity+1 WHERE id=$1",
            UUID(slot_id),
        )


def test_concurrent_changed_payload_uses_one_key(
    integration_client, integration_settings, auth_keys
):
    client = integration_client
    _, body, _ = prepare(client, auth_keys[0])
    owner = auth(auth_keys[0])
    key = uuid4()
    changed = {
        **body,
        "items": [{**body["items"][0], "quantity": 1}],
        "expected_total_amount": 12000,
    }
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda value: submit(client, value, owner, key), [body, changed]))
    assert sorted(r.status_code for r in responses) == [201, 409]
    assert counts(integration_settings)["orders"] == counts(integration_settings)["events"] == 1


def test_expired_snapshot_rolls_back_claim(integration_client, integration_settings, auth_keys):
    client = integration_client
    _, body, _ = prepare(client, auth_keys[0])
    owner = auth(auth_keys[0])
    original = client.app.state.menu.snapshot

    async def slow(ids):
        await asyncio.sleep(0.03)
        return await original(ids)

    client.app.state.menu.snapshot = slow
    client.app.state.settings.snapshot_max_age_seconds = 0.001
    response = submit(client, body, owner)
    assert response.status_code == 503 and response.json()["detail"]["code"] == "SNAPSHOT_EXPIRED"
    assert all(value == 0 for value in counts(integration_settings).values())


def test_slot_lock_timeout_rolls_back_claim(integration_client, integration_settings, auth_keys):
    import threading

    client = integration_client
    _, body, slot_id = prepare(client, auth_keys[0])
    owner = auth(auth_keys[0])
    client.app.state.settings.transaction_lock_timeout_ms = 50
    entered, release = threading.Event(), threading.Event()

    async def hold_lock():
        connection = await asyncpg.connect(
            integration_settings.database_url.get_secret_value().replace(
                "postgresql+asyncpg://", "postgresql://"
            )
        )
        try:
            async with connection.transaction():
                await connection.execute(
                    "SELECT id FROM time_slots WHERE id=$1 FOR UPDATE", UUID(slot_id)
                )
                entered.set()
                await asyncio.to_thread(release.wait, 5)
        finally:
            await connection.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, hold_lock())
        try:
            assert entered.wait(3)
            assert submit(client, body, owner).status_code == 503
        finally:
            release.set()
            future.result(timeout=5)
    assert all(value == 0 for value in counts(integration_settings).values())
