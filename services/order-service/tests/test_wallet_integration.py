from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import asyncpg
import pytest
from conftest import auth
from fastapi.testclient import TestClient
from test_order_integration import counts, db_query, prepare, submit

from order_service.main import create_app

pytestmark = pytest.mark.integration


def credit(client, private, user_id, amount=24000, key=None):
    return client.post(
        "/wallet/credits",
        headers={**auth(private, "ADMIN"), "Idempotency-Key": str(key or uuid4())},
        json={"user_id": str(user_id), "amount": amount},
    )


@pytest.fixture
def demo(integration_client):
    integration_client.app.state.settings.demo_payments_enabled = True
    return integration_client


def test_credit_replay_conflict_and_read_isolation(demo, auth_keys):
    user_id, key = uuid4(), uuid4()
    owner = auth(auth_keys[0], user_id=user_id)
    assert demo.get("/wallet", headers=owner).json()["balance"] == 0
    first = credit(demo, auth_keys[0], user_id, key=key)
    assert first.status_code == 201, first.text
    assert credit(demo, auth_keys[0], user_id, key=key).json() == first.json()
    assert credit(demo, auth_keys[0], user_id, 1, key).status_code == 409
    assert credit(demo, auth_keys[0], uuid4(), key=key).status_code == 409
    assert demo.get("/wallet", headers=owner).json()["balance"] == 24000
    assert demo.get("/wallet", headers=auth(auth_keys[0])).json()["balance"] == 0


def test_checkout_replay_refund_once_even_after_disabling_demo(
    demo, integration_settings, auth_keys
):
    _, body, _ = prepare(demo, auth_keys[0])
    user_id = uuid4()
    owner = auth(auth_keys[0], user_id=user_id)
    assert credit(demo, auth_keys[0], user_id).status_code == 201
    key = uuid4()
    created = submit(demo, body, owner, key)
    assert created.status_code == 201, created.text
    assert created.json()["payment_status"] == "DEMO_PAID"
    assert submit(demo, body, owner, key).json() == created.json()
    assert demo.get("/wallet", headers=owner).json()["balance"] == 0
    demo.app.state.settings.demo_payments_enabled = False
    order_id = created.json()["id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(
            pool.map(
                lambda _: demo.post(
                    f"/{order_id}/cancel", headers=owner, json={"expected_version": 1}
                ),
                range(4),
            )
        )
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert all(r.json()["payment_status"] == "DEMO_REFUNDED" for r in responses)
    assert demo.get("/wallet", headers=owner).json()["balance"] == 24000
    assert counts(integration_settings)["reservations"] == 0
    assert db_query(integration_settings, "SELECT kind FROM demo_ledger ORDER BY created_at") == [
        {"kind": "CREDIT"},
        {"kind": "DEBIT"},
        {"kind": "REFUND"},
    ]


def test_insufficient_funds_and_concurrent_checkout(demo, integration_settings, auth_keys):
    _, body, _ = prepare(demo, auth_keys[0])
    user_id = uuid4()
    owner = auth(auth_keys[0], user_id=user_id)
    failed = submit(demo, body, owner)
    assert failed.status_code == 409 and failed.json()["detail"]["code"] == "INSUFFICIENT_FUNDS"
    assert all(value == 0 for value in counts(integration_settings).values())
    assert credit(demo, auth_keys[0], user_id).status_code == 201
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: submit(demo, body, owner), range(4)))
    assert sorted(r.status_code for r in responses) == [201, 409, 409, 409]
    assert counts(integration_settings)["orders"] == 1
    assert demo.get("/wallet", headers=owner).json()["balance"] == 0


def test_outbox_failure_rolls_back_debit_and_refund(demo, integration_settings, auth_keys):
    _, body, _ = prepare(demo, auth_keys[0])
    user_id = uuid4()
    owner = auth(auth_keys[0], user_id=user_id)
    assert credit(demo, auth_keys[0], user_id).status_code == 201
    db_query(
        integration_settings,
        "ALTER TABLE outbox_events ADD CONSTRAINT reject_payment_event CHECK (false) NOT VALID",
    )
    try:
        assert submit(demo, body, owner).status_code == 503
        assert demo.get("/wallet", headers=owner).json()["balance"] == 24000
        assert all(value == 0 for value in counts(integration_settings).values())
    finally:
        db_query(
            integration_settings, "ALTER TABLE outbox_events DROP CONSTRAINT reject_payment_event"
        )
    created = submit(demo, body, owner).json()
    db_query(
        integration_settings,
        "ALTER TABLE outbox_events ADD CONSTRAINT reject_payment_event CHECK (false) NOT VALID",
    )
    try:
        assert (
            demo.post(
                f"/{created['id']}/cancel", headers=owner, json={"expected_version": 1}
            ).status_code
            == 503
        )
        assert demo.get("/wallet", headers=owner).json()["balance"] == 0
        assert counts(integration_settings)["reservations"] == 1
    finally:
        db_query(
            integration_settings, "ALTER TABLE outbox_events DROP CONSTRAINT reject_payment_event"
        )


def test_concurrent_credit_is_idempotent_and_audited(demo, integration_settings, auth_keys):
    user_id, key = uuid4(), uuid4()
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: credit(demo, auth_keys[0], user_id, key=key), range(4)))
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1
    assert (
        db_query(
            integration_settings, "SELECT balance FROM demo_wallets WHERE user_id=$1", user_id
        )[0]["balance"]
        == 24000
    )


@pytest.mark.parametrize("amount", [0, -1, True, "100", 1.5, 2**31])
def test_invalid_credit(demo, auth_keys, amount):
    assert credit(demo, auth_keys[0], uuid4(), amount).status_code == 422


def test_credit_limit_leaves_refund_headroom(demo, auth_keys):
    user_id = uuid4()
    assert credit(demo, auth_keys[0], user_id, 2**31 - 1).status_code == 201
    assert credit(demo, auth_keys[0], user_id, 1).status_code == 409


def test_concurrent_duplicate_checkout_debits_once(demo, integration_settings, auth_keys):
    _, body, _ = prepare(demo, auth_keys[0])
    user_id, key = uuid4(), uuid4()
    owner = auth(auth_keys[0], user_id=user_id)
    assert credit(demo, auth_keys[0], user_id).status_code == 201
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: submit(demo, body, owner, key), range(4)))
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1
    assert counts(integration_settings)["orders"] == 1
    assert (
        db_query(integration_settings, "SELECT count(*) AS n FROM demo_ledger WHERE kind='DEBIT'")[
            0
        ]["n"]
        == 1
    )


def test_restart_preserves_credit_and_checkout_replay(demo, integration_settings, auth_keys):
    _, body, _ = prepare(demo, auth_keys[0])
    user_id, credit_key, checkout_key = uuid4(), uuid4(), uuid4()
    owner = auth(auth_keys[0], user_id=user_id)
    first_credit = credit(demo, auth_keys[0], user_id, key=credit_key)
    first_order = submit(demo, body, owner, checkout_key)
    with TestClient(create_app(integration_settings)) as restarted:
        assert (
            credit(restarted, auth_keys[0], user_id, key=credit_key).json() == first_credit.json()
        )
        assert submit(restarted, body, owner, checkout_key).json() == first_order.json()
        assert restarted.get("/wallet", headers=owner).json()["balance"] == 0


def test_credit_ledger_failure_rolls_back_balance_and_claim(demo, integration_settings, auth_keys):
    user_id, key = uuid4(), uuid4()
    db_query(
        integration_settings,
        "ALTER TABLE demo_ledger ADD CONSTRAINT reject_credit CHECK (false) NOT VALID",
    )
    try:
        assert credit(demo, auth_keys[0], user_id, key=key).status_code == 503
        assert (
            db_query(integration_settings, "SELECT count(*) AS n FROM demo_credit_requests")[0]["n"]
            == 0
        )
        assert db_query(integration_settings, "SELECT count(*) AS n FROM demo_wallets")[0]["n"] == 0
    finally:
        db_query(integration_settings, "ALTER TABLE demo_ledger DROP CONSTRAINT reject_credit")
    assert credit(demo, auth_keys[0], user_id, key=key).status_code == 201


def test_rejected_checkout_and_cancel_never_move_funds(demo, integration_settings, auth_keys):
    _, body, slot_id = prepare(demo, auth_keys[0], capacity=1)
    user_id = uuid4()
    owner = auth(auth_keys[0], user_id=user_id)
    assert credit(demo, auth_keys[0], user_id, 48000).status_code == 201
    assert submit(demo, {**body, "expected_total_amount": 1}, owner).status_code == 409
    assert demo.get("/wallet", headers=owner).json()["balance"] == 48000
    created = submit(demo, body, owner).json()
    assert submit(demo, body, owner).status_code == 409
    assert (
        demo.post(
            f"/{created['id']}/cancel", headers=auth(auth_keys[0]), json={"expected_version": 1}
        ).status_code
        == 404
    )
    assert (
        demo.post(
            f"/{created['id']}/cancel",
            headers=auth(auth_keys[0], "COOK"),
            json={"expected_version": 1},
        ).status_code
        == 403
    )
    db_query(
        integration_settings,
        "UPDATE time_slots SET start_time=now()-interval '1 minute' WHERE id=$1",
        UUID(slot_id),
    )
    assert (
        demo.post(
            f"/{created['id']}/cancel", headers=owner, json={"expected_version": 1}
        ).status_code
        == 409
    )
    assert demo.get("/wallet", headers=owner).json()["balance"] == 24000
    assert demo.get(f"/{created['id']}", headers=owner).json()["payment_status"] == "DEMO_PAID"
    assert (
        db_query(integration_settings, "SELECT count(*) AS n FROM demo_ledger WHERE kind='REFUND'")[
            0
        ]["n"]
        == 0
    )


def test_simultaneous_credit_cancel_and_checkout_preserve_ledger(
    demo, integration_settings, auth_keys
):
    _, body, _ = prepare(demo, auth_keys[0])
    user_id = uuid4()
    owner = auth(auth_keys[0], user_id=user_id)
    assert credit(demo, auth_keys[0], user_id, 48000).status_code == 201
    order_id = submit(demo, body, owner).json()["id"]
    actions = [
        lambda: credit(demo, auth_keys[0], user_id, 100),
        lambda: submit(demo, body, owner),
        lambda: demo.post(f"/{order_id}/cancel", headers=owner, json={"expected_version": 1}),
    ]
    with ThreadPoolExecutor(max_workers=3) as pool:
        responses = list(pool.map(lambda action: action(), actions))
    assert sorted(r.status_code for r in responses) == [200, 201, 201], [r.text for r in responses]
    balance = demo.get("/wallet", headers=owner).json()["balance"]
    total = db_query(
        integration_settings,
        "SELECT sum(CASE WHEN kind='DEBIT' THEN -amount ELSE amount END) AS balance "
        "FROM demo_ledger WHERE user_id=$1",
        user_id,
    )[0]["balance"]
    assert balance == total == 24100


def test_audit_entries_cannot_be_edited_or_deleted(demo, integration_settings, auth_keys):
    assert credit(demo, auth_keys[0], uuid4()).status_code == 201
    for sql in ["UPDATE demo_ledger SET amount=1", "DELETE FROM demo_ledger"]:
        with pytest.raises(asyncpg.CheckViolationError):
            db_query(integration_settings, sql)


def test_legacy_order_does_not_mint_a_refund_when_demo_enabled(
    demo, integration_settings, auth_keys
):
    demo.app.state.settings.demo_payments_enabled = False
    _, body, _ = prepare(demo, auth_keys[0])
    owner = auth(auth_keys[0])
    created = submit(demo, body, owner).json()
    assert created["payment_status"] == "NOT_REQUIRED"
    demo.app.state.settings.demo_payments_enabled = True
    cancelled = demo.post(f"/{created['id']}/cancel", headers=owner, json={"expected_version": 1})
    assert cancelled.status_code == 200 and cancelled.json()["payment_status"] == "NOT_REQUIRED"
    assert demo.get("/wallet", headers=owner).json()["balance"] == 0
    assert db_query(integration_settings, "SELECT count(*) AS n FROM demo_ledger")[0]["n"] == 0


def test_zero_total_checkout_and_refund_need_no_credit(demo, integration_settings, auth_keys):
    from order_service.domain.orders import DishSnapshot

    _, body, _ = prepare(demo, auth_keys[0])
    dish_id = UUID(body["items"][0]["menu_item_id"])
    demo.app.state.menu.dishes[dish_id] = DishSnapshot(dish_id, "Бесплатно", 0)
    body["expected_total_amount"] = 0
    owner = auth(auth_keys[0])
    created = submit(demo, body, owner)
    assert created.status_code == 201 and created.json()["payment_status"] == "DEMO_PAID"
    assert (
        demo.post(
            f"/{created.json()['id']}/cancel", headers=owner, json={"expected_version": 1}
        ).status_code
        == 200
    )
    assert demo.get("/wallet", headers=owner).json()["balance"] == 0


def test_admin_refunds_preparing_but_completed_order_cannot_refund(demo, auth_keys):
    admin, body, _ = prepare(demo, auth_keys[0])
    user_id = uuid4()
    owner = auth(auth_keys[0], user_id=user_id)
    assert credit(demo, auth_keys[0], user_id, 48000).status_code == 201
    first = submit(demo, body, owner).json()["id"]
    assert (
        demo.patch(
            f"/{first}/status", headers=admin, json={"status": "PREPARING", "expected_version": 1}
        ).status_code
        == 200
    )
    cancelled = demo.post(f"/{first}/cancel", headers=admin, json={"expected_version": 2})
    assert cancelled.status_code == 200 and cancelled.json()["payment_status"] == "DEMO_REFUNDED"
    second = submit(demo, body, owner).json()["id"]
    for version, status in enumerate(["PREPARING", "READY", "COMPLETED"], start=1):
        response = demo.patch(
            f"/{second}/status", headers=admin, json={"status": status, "expected_version": version}
        )
        assert response.status_code == 200 and response.json()["payment_status"] == "DEMO_PAID"
    assert (
        demo.post(f"/{second}/cancel", headers=admin, json={"expected_version": 4}).status_code
        == 409
    )
    assert demo.get("/wallet", headers=owner).json()["balance"] == 24000
