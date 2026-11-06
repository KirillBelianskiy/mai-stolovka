from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from order_service.api.dependencies import Claims, Session
from order_service.application.schemas import DemoCreditInput, DemoCreditRead, WalletRead
from order_service.application.service import lock_settings
from order_service.application.wallet import credit_wallet
from order_service.infrastructure.models import DemoWallet
from order_service.infrastructure.tokens import AccessClaims

router = APIRouter(prefix="/wallet", tags=["demo payments"])


async def demo_admin(claims: Claims, request: Request) -> AccessClaims:
    if claims.role != "ADMIN":
        raise HTTPException(403, "Administrator role required")
    if not request.app.state.settings.demo_payments_enabled:
        raise HTTPException(403, "Demo payments are disabled")
    return claims


@router.get("", response_model=WalletRead)
async def balance(claims: Claims, db: Session, request: Request) -> JSONResponse:
    wallet = await db.get(DemoWallet, claims.sub)
    result = WalletRead(
        user_id=claims.sub,
        balance=wallet.balance if wallet else 0,
        checkout_payment_enabled=request.app.state.settings.demo_payments_enabled,
    )
    return JSONResponse(
        content=result.model_dump(mode="json"), headers={"Cache-Control": "no-store"}
    )


@router.post(
    "/credits",
    response_model=DemoCreditRead,
    status_code=201,
    summary="Credit synthetic demo funds (ADMIN only)",
)
async def credit(
    admin: Annotated[AccessClaims, Depends(demo_admin)],
    body: DemoCreditInput,
    request: Request,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> JSONResponse:
    database = request.app.state.database
    if database is None:
        raise HTTPException(503, "Database is unavailable")
    async with database.sessions() as db, db.begin():
        await lock_settings(db, request.app.state.settings)
        result, replayed = await credit_wallet(db, admin.sub, idempotency_key, body)
    return JSONResponse(
        status_code=201,
        content=result,
        headers={
            "Idempotency-Replayed": str(replayed).lower(),
            "Cache-Control": "no-store",
        },
    )
