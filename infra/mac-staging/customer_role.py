"""Caddy authorization check for authenticated customer routes."""

import jwt
from fastapi import FastAPI, Request, Response
from pydantic import ValidationError
from user_service.config import Settings
from user_service.infrastructure.tokens import TokenVerifier


def create_app() -> FastAPI:
    verifier = TokenVerifier(Settings())
    if verifier.public_key is None:
        raise RuntimeError("A staging JWT public key is required")
    app = FastAPI(openapi_url=None)

    @app.get("/client")
    def client(request: Request) -> Response:
        credentials = request.headers.getlist("authorization")
        if len(credentials) == 1:
            scheme, _, token = credentials[0].partition(" ")
            if scheme.lower() == "bearer" and token:
                try:
                    claims = verifier.verify(token)
                except (jwt.PyJWTError, ValidationError, ValueError):
                    pass
                else:
                    return Response(status_code=204 if claims.role == "CLIENT" else 403)
        return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})

    return app
