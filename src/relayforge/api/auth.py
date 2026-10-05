from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Request

from relayforge.core.auth import AuthService
from relayforge.settings import Settings

SESSION_COOKIE = "rf_session"
CSRF_COOKIE = "rf_csrf"


def trusted_proxy(request: Request) -> bool:
    if request.client is None:
        return False
    peer = request.client.host
    if peer in {"127.0.0.1", "::1", "testclient"}:
        return True
    settings = getattr(request.app.state, "settings", None)
    return bool(
        settings is not None
        and getattr(settings, "container_mode", False)
        and peer == getattr(settings, "trusted_proxy_ip", "")
    )


def tailscale_login(request: Request) -> str:
    if not trusted_proxy(request):
        return ""
    return request.headers.get("tailscale-user-login", "").strip().lower()


def allowed_host(request: Request, settings: Settings) -> bool:
    host = request.headers.get("host", "")
    parsed = urlsplit(f"//{host}")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return hostname in {"localhost", "127.0.0.1", *settings.allowed_hosts}


def expected_origin(request: Request) -> str:
    scheme = request.url.scheme
    if trusted_proxy(request):
        forwarded = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
        if forwarded in {"http", "https"}:
            scheme = forwarded
    # This value is only compared with Origin; it is not rendered into HTML.
    # nosemgrep: python.flask.security.audit.directly-returned-format-string.directly-returned-format-string
    return f"{scheme}://{request.headers.get('host', '')}"


def origin_is_valid(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return False
    parsed = urlsplit(origin)
    return parsed.scheme in {"http", "https"} and origin.rstrip("/") == expected_origin(request)


def stream_origin_is_valid(request: Request) -> bool:
    """Validate browser EventSource requests, which omit Origin on same-origin GETs."""
    origin = request.headers.get("origin")
    if origin:
        return origin_is_valid(request)
    return request.headers.get("sec-fetch-site", "").lower() == "same-origin"


def csrf_is_valid(request: Request) -> bool:
    cookie = request.cookies.get(CSRF_COOKIE, "")
    header = request.headers.get("x-csrf-token", "")
    return cookie != "" and cookie == header


def authenticated(request: Request, settings: Settings, auth: AuthService) -> bool:
    login = tailscale_login(request)
    if not login or login not in settings.allowed_tailscale_logins:
        return False
    token = request.cookies.get(SESSION_COOKIE, "")
    return bool(token) and auth.is_valid(token, login)
