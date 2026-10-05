from __future__ import annotations

import secrets
from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from relayforge.api.auth import CSRF_COOKIE, SESSION_COOKIE, tailscale_login
from relayforge.core.auth import AuthService
from relayforge.settings import Settings

router = APIRouter(prefix="/api/auth")


class PairBody(BaseModel):
    code: str = Field(min_length=20, max_length=100)


def _service(request: Request) -> AuthService:
    return cast(AuthService, request.app.state.auth)


@router.get("/status")
def auth_status(request: Request) -> dict[str, bool]:
    settings = cast(Settings, request.app.state.settings)
    login = tailscale_login(request)
    return {
        "authenticated": bool(
            login
            and _service(request).is_valid(request.cookies.get(SESSION_COOKIE, ""), login)
            and login in settings.allowed_tailscale_logins
        )
    }


@router.get("/csrf")
def csrf_token() -> Response:
    token = secrets.token_urlsafe(32)
    response = JSONResponse({"csrf_token": token})
    response.set_cookie(
        CSRF_COOKIE, token, httponly=False, secure=True, samesite="strict", path="/", max_age=600
    )
    return response


@router.post("/pair")
def pair(request: Request, body: PairBody) -> Response:
    settings = cast(Settings, request.app.state.settings)
    login = tailscale_login(request)
    if not login or login not in settings.allowed_tailscale_logins:
        return JSONResponse(
            {"error": {"code": "identity_denied", "message": "Identidad no permitida."}}, status_code=403
        )
    session_token = _service(request).pair(body.code, login)
    if session_token is None:
        return JSONResponse(
            {"error": {"code": "pairing_rejected", "message": "Código inválido o vencido."}}, status_code=403
        )
    response = JSONResponse({"authenticated": True})
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        httponly=True,
        secure=True,
        samesite="strict",
        path="/",
        max_age=14 * 24 * 60 * 60,
    )
    return response


@router.post("/logout")
def logout(request: Request) -> Response:
    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        _service(request).revoke(token)
    response = JSONResponse({"authenticated": False})
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    response.delete_cookie(CSRF_COOKIE, path="/", secure=True, samesite="strict")
    return response
