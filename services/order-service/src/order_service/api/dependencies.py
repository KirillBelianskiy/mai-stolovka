from collections.abc import AsyncIterator
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from order_service.infrastructure.tokens import AccessClaims

bearer = HTTPBearer(auto_error=False)


async def access_claims(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> AccessClaims:
    if credentials is None:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    try:
        claims: AccessClaims = request.app.state.tokens.verify(credentials.credentials)
        return claims
    except RuntimeError:
        raise HTTPException(503, "Authentication is not configured") from None
    except (jwt.PyJWTError, ValidationError, ValueError):
        raise HTTPException(
            401, "Invalid access token", headers={"WWW-Authenticate": "Bearer"}
        ) from None


async def session(request: Request) -> AsyncIterator[AsyncSession]:
    database = request.app.state.database
    if database is None:
        raise HTTPException(503, "Database is unavailable")
    async with database.sessions() as current:
        yield current


Session = Annotated[AsyncSession, Depends(session)]
Claims = Annotated[AccessClaims, Depends(access_claims)]
