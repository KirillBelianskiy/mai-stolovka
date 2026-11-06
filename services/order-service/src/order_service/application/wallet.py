from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from order_service.application.schemas import MAX_INTEGER, DemoCreditInput, DemoCreditRead
from order_service.domain.orders import OrderError
from order_service.infrastructure.models import DemoCreditRequest, DemoLedger, DemoWallet


async def lock_wallet(db: AsyncSession, user_id: UUID) -> DemoWallet:
    await db.execute(insert(DemoWallet).values(user_id=user_id).on_conflict_do_nothing())
    wallet = await db.scalar(
        select(DemoWallet).where(DemoWallet.user_id == user_id).with_for_update()
    )
    assert wallet is not None
    return wallet


async def credit_wallet(
    db: AsyncSession, actor_id: UUID, key: UUID, body: DemoCreditInput
) -> tuple[dict[str, Any], bool]:
    claimed = await db.scalar(
        insert(DemoCreditRequest)
        .values(key=key, user_id=body.user_id, amount=body.amount, actor_id=actor_id)
        .on_conflict_do_nothing()
        .returning(DemoCreditRequest.key)
    )
    record = await db.get(DemoCreditRequest, key)
    assert record is not None
    if claimed is None:
        if (record.user_id, record.amount) != (body.user_id, body.amount):
            raise OrderError(409, "IDEMPOTENCY_CONFLICT", "Credit key used for another request")
        if record.response_body is None:
            raise OrderError(503, "INCOMPLETE_CREDIT", "Credit response unavailable; retry safely")
        return record.response_body, True
    wallet = await lock_wallet(db, body.user_id)
    # A lifetime credit ceiling guarantees headroom for every outstanding cancellation refund.
    if wallet.total_credited + body.amount > MAX_INTEGER:
        raise OrderError(409, "DEMO_CREDIT_LIMIT", "Demo wallet lifetime credit limit exceeded")
    wallet.balance += body.amount
    wallet.total_credited += body.amount
    entry = DemoLedger(
        user_id=body.user_id,
        kind="CREDIT",
        amount=body.amount,
        credit_key=key,
        actor_id=actor_id,
    )
    db.add(entry)
    await db.flush()
    response = DemoCreditRead(
        id=entry.id, user_id=body.user_id, amount=body.amount, balance_after=wallet.balance
    ).model_dump(mode="json")
    record.response_body = response
    return response, False


async def debit_wallet(db: AsyncSession, user_id: UUID, order_id: UUID, amount: int) -> None:
    wallet = await lock_wallet(db, user_id)
    if wallet.balance < amount:
        raise OrderError(409, "INSUFFICIENT_FUNDS", "Insufficient demo balance")
    wallet.balance -= amount
    db.add(DemoLedger(user_id=user_id, kind="DEBIT", amount=amount, order_id=order_id))


async def refund_wallet(db: AsyncSession, user_id: UUID, order_id: UUID, amount: int) -> None:
    wallet = await lock_wallet(db, user_id)
    wallet.balance += amount
    db.add(DemoLedger(user_id=user_id, kind="REFUND", amount=amount, order_id=order_id))
