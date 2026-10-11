from __future__ import annotations

import mimetypes
import secrets
import threading
import time
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import Request, WebSocket
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute

from relayforge.api.auth import allowed_host, tailscale_login
from relayforge.core.deliverables import DeliverableError, Root, resolve
from relayforge.core.previews import PreviewService
from relayforge.settings import Settings

_MAX_REQUEST_BYTES = 32 * 1024 * 1024
_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


class PreviewGateway:
    def __init__(self, settings: Settings, previews: PreviewService) -> None:
        self.settings = settings
        self.previews = previews
        self._tickets: dict[str, tuple[str, float]] = {}
        self._sessions: dict[str, str] = {}
        self._lock = threading.Lock()

    def issue_ticket(self, preview_id: str) -> str:
        if not self.previews.access_allowed(preview_id):
            raise ValueError("preview_not_running")
        token = secrets.token_hex(32)
        with self._lock:
            self._tickets[token] = (preview_id, time.monotonic() + 120)
        return f"{self.settings.preview_public_origin}/__rf/open/{token}"

    def redeem_ticket(self, token: str) -> tuple[str, str] | None:
        with self._lock:
            ticket = self._tickets.pop(token, None)
            if ticket is None or ticket[1] < time.monotonic():
                return None
            preview_id = ticket[0]
            if not self.previews.access_allowed(preview_id):
                return None
            cookie = secrets.token_urlsafe(32)
            self._sessions[cookie] = preview_id
        return cookie, preview_id

    def preview_for_cookie(self, cookie: str) -> str | None:
        with self._lock:
            return self._sessions.get(cookie)

    def revoke_preview(self, preview_id: str) -> None:
        with self._lock:
            self._tickets = {
                ticket: value for ticket, value in self._tickets.items() if value[0] != preview_id
            }
            self._sessions = {
                token: current for token, current in self._sessions.items() if current != preview_id
            }


def create_preview_gateway(
    settings: Settings, previews: PreviewService, gateway: PreviewGateway
) -> Starlette:
    app = Starlette(
        routes=[
            Route("/__rf/open/{ticket:str}", _open_ticket, methods=["GET"]),
            Route(
                "/{path:path}",
                _serve_preview,
                methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            ),
            WebSocketRoute("/{path:path}", _reject_websocket),
        ]
    )
    app.state.settings = settings
    app.state.previews = previews
    app.state.preview_gateway = gateway

    async def gateway_security(request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not allowed_host(request, settings):
            response = Response(status_code=400)
        else:
            login = tailscale_login(request)
            if not login or login not in settings.allowed_tailscale_logins:
                response = Response(status_code=404, content="Not found")
            else:
                response = await call_next(request)
        parsed = urlsplit(settings.preview_public_origin)
        forwarded_scheme = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip()
        scheme = forwarded_scheme if forwarded_scheme in {"http", "https"} else parsed.scheme
        if parsed.hostname in {"localhost", "127.0.0.1"}:
            console_origin = f"{scheme}://{parsed.hostname}:{settings.port}"
        else:
            console_origin = f"{scheme}://{parsed.hostname}"
        response.headers["Content-Security-Policy"] = f"frame-ancestors 'self' {console_origin}"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        return response

    app.add_middleware(BaseHTTPMiddleware, dispatch=gateway_security)
    return app


async def _open_ticket(request: Request) -> Response:
    gateway: PreviewGateway = request.app.state.preview_gateway
    redeemed = gateway.redeem_ticket(request.path_params["ticket"])
    if redeemed is None:
        return Response("Not found", status_code=404)
    cookie, _ = redeemed
    response = RedirectResponse("/", status_code=303, headers={"Cache-Control": "no-store"})
    response.set_cookie(
        "rf_preview",
        cookie,
        httponly=True,
        secure=request.app.state.settings.preview_public_origin.startswith("https://"),
        samesite="lax",
        path="/",
    )
    return response


async def _serve_preview(request: Request) -> Response:
    gateway: PreviewGateway = request.app.state.preview_gateway
    previews: PreviewService = request.app.state.previews
    preview_id = gateway.preview_for_cookie(request.cookies.get("rf_preview", ""))
    if preview_id is None or not previews.access_allowed(preview_id):
        return Response("Not found", status_code=404)
    data = previews.gateway_preview(preview_id)
    if data is None:
        return Response("Not found", status_code=404)
    previews.touch(preview_id)
    if request.headers.get("upgrade", "").lower() == "websocket":
        return Response(status_code=501)
    if data["kind"] == "static":
        return _static_response(data["root_path"], request.path_params.get("path", ""))
    return await _proxy_response(request, data["port"])


def _static_response(root_path: str, rel: str) -> Response:
    root = Root("preview", "preview", Path(root_path))
    rel = rel or "index.html"
    try:
        path = resolve(root, rel)
        if path.is_dir():
            rel = f"{rel.rstrip('/')}/index.html"
            path = resolve(root, rel)
        if not path.is_file():
            return Response("Not found", status_code=404)
    except DeliverableError:
        return Response("Not found", status_code=404)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(
        path,
        media_type=media_type,
        headers={"X-Content-Type-Options": "nosniff"},
    )


async def _proxy_response(request: Request, port: int | None) -> Response:
    if port is None:
        return Response(status_code=502)
    try:
        declared_size = int(request.headers.get("content-length", "0"))
    except ValueError:
        return Response(status_code=400)
    if declared_size > _MAX_REQUEST_BYTES:
        return Response(status_code=413)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > _MAX_REQUEST_BYTES:
            return Response(status_code=413)
    headers = _request_headers(request)
    target = f"http://127.0.0.1:{port}{request.url.path}"
    if request.url.query:
        target += "?" + request.url.query
    client = httpx.AsyncClient(timeout=60, trust_env=False)
    try:
        upstream_request = client.build_request(
            request.method,
            target,
            headers=headers,
            content=bytes(body),
        )
        upstream = await client.send(upstream_request, stream=True)
    except httpx.TimeoutException:
        await client.aclose()
        return Response(status_code=504)
    except httpx.HTTPError:
        await client.aclose()
        return Response(status_code=502)

    safe_headers = _response_headers(upstream)

    async def stream() -> AsyncIterator[bytes]:
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    response = StreamingResponse(stream(), status_code=upstream.status_code)
    response.raw_headers.extend(safe_headers)
    response.background = BackgroundTask(upstream.aclose)
    return response


def _request_headers(request: Request) -> list[tuple[str, str]]:
    connection_tokens = {
        item.strip().lower() for item in request.headers.get("connection", "").split(",") if item.strip()
    }
    headers: list[tuple[str, str]] = []
    for name, value in request.headers.items():
        lower = name.lower()
        if (
            lower in _HOP_BY_HOP
            or lower in connection_tokens
            or lower == "host"
            or lower.startswith("tailscale-")
            or lower.startswith("x-forwarded-")
        ):
            continue
        if lower == "cookie":
            retained = [
                item.strip()
                for item in value.split(";")
                if item.strip().split("=", 1)[0].strip().lower()
                not in {"rf_session", "rf_csrf", "rf_preview"}
            ]
            if retained:
                headers.append((name, "; ".join(retained)))
            continue
        headers.append((name, value))
    return headers


def _response_headers(upstream: httpx.Response) -> list[tuple[bytes, bytes]]:
    connection_tokens = {
        item.strip().lower() for item in upstream.headers.get("connection", "").split(",") if item.strip()
    }
    result: list[tuple[bytes, bytes]] = []
    for name, value in upstream.headers.multi_items():
        lower = name.lower()
        if lower in _HOP_BY_HOP or lower in connection_tokens:
            continue
        if lower == "set-cookie" and value.split("=", 1)[0].strip().lower().startswith("rf_"):
            continue
        result.append((name.encode("latin-1"), value.encode("latin-1")))
    return result


async def _reject_websocket(websocket: WebSocket) -> None:
    await websocket.close(code=1003)
