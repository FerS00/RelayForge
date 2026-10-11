from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from sqlalchemy import text


def _start_command_preview(app) -> dict[str, object]:
    workspace = Path(app.state.settings.workspace_dir)
    fake = Path(__file__).resolve().parents[1] / "fakes" / "fake_preview_server.py"
    (workspace / "relayforge-preview.json").write_text(
        json.dumps({"argv": ["python", str(fake)], "ready_path": "/"}),
        encoding="utf-8",
    )
    app.state.previews.set_gateway_state(True)
    conversation = app.state.chat.create_conversation("codex")
    return asyncio.run(app.state.previews.start(conversation["id"], "workspace", "", None))


def test_gateway_ticket_is_one_use_and_preview_cookies_are_sanitized(client, app) -> None:
    preview = _start_command_preview(app)
    gateway = app.state.preview_gateway
    gateway_app = app.state.preview_gateway_app
    headers = {"Host": "localhost", "Tailscale-User-Login": "owner@example.test"}
    try:
        with TestClient(gateway_app, base_url="http://localhost:8793", headers=headers) as gateway_client:
            without_session = gateway_client.get("/")
            assert without_session.status_code == 404

            ticket_url = gateway.issue_ticket(str(preview["preview_id"]))
            ticket_path = urlsplit(ticket_url).path
            opened = gateway_client.get(ticket_path, follow_redirects=False)
            assert opened.status_code == 303
            assert opened.headers["location"] == "/"
            cookie = opened.headers["set-cookie"]
            assert "rf_preview=" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie

            replay = gateway_client.get(ticket_path)
            assert replay.status_code == 404
            gateway_client.cookies.set("rf_session", "console-session", domain="localhost", path="/")
            gateway_client.cookies.set("rf_csrf", "console-csrf", domain="localhost", path="/")
            echoed = gateway_client.get("/headers").json()
            assert echoed == {"cookie": "", "tailscale": "", "forwarded": ""}

            cookies = gateway_client.get("/cookies")
            set_cookies = cookies.headers.get_list("set-cookie")
            assert all(not item.lower().startswith("rf_") for item in set_cookies)
            assert any(item.startswith("preview_ok=") for item in set_cookies)
            assert (
                cookies.headers["content-security-policy"] == "frame-ancestors 'self' http://127.0.0.1:8787"
            )
            assert cookies.headers["referrer-policy"] == "no-referrer"
            assert cookies.headers["cross-origin-opener-policy"] == "same-origin"

            expired_url = gateway.issue_ticket(str(preview["preview_id"]))
            expired_token = urlsplit(expired_url).path.rsplit("/", 1)[1]
            with gateway._lock:
                gateway._tickets[expired_token] = (str(preview["preview_id"]), time.monotonic() - 1)
            assert gateway_client.get(urlsplit(expired_url).path).status_code == 404
    finally:
        asyncio.run(app.state.previews.stop(str(preview["preview_id"]), "test_cleanup"))


def test_console_rejects_preview_origin_for_mutations(client, app) -> None:
    response = client.post(
        "/api/previews/unknown/stop",
        json={},
        headers={"Origin": "https://localhost:8443"},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden_origin"


def test_console_ticket_response_contains_url_but_events_do_not(client, app) -> None:
    workspace = Path(app.state.settings.workspace_dir)
    (workspace / "index.html").write_text("<h1>Static</h1>", encoding="utf-8")
    app.state.previews.set_gateway_state(True)
    conversation = app.state.chat.create_conversation("codex")
    result = asyncio.run(app.state.previews.start(conversation["id"], "workspace", "", None))
    preview_id = str(result["preview_id"])
    try:
        gateway_url = app.state.preview_gateway.issue_ticket(preview_id)
        with TestClient(
            app.state.preview_gateway_app,
            base_url="http://localhost:8793",
            headers={"Host": "localhost", "Tailscale-User-Login": "owner@example.test"},
        ) as gateway_client:
            opened = gateway_client.get(urlsplit(gateway_url).path, follow_redirects=False)
            assert opened.status_code == 303
            served = gateway_client.get("/")
            assert served.status_code == 200
            assert served.text == "<h1>Static</h1>"
            assert served.headers["content-type"].startswith("text/html")
            assert served.headers["x-content-type-options"] == "nosniff"
            assert served.headers["referrer-policy"] == "no-referrer"

        response = client.post(f"/api/previews/{preview_id}/ticket", json={})
        assert response.status_code == 200
        assert response.json()["expires_in"] == 120
        ticket_url = response.json()["url"]
        assert ticket_url.startswith(app.state.settings.preview_public_origin + "/__rf/open/")
        with app.state.actions.sessions() as session:
            events = session.execute(
                text("SELECT payload_json FROM events WHERE conversation_id=:cid AND type='preview.updated'"),
                {"cid": conversation["id"]},
            ).scalars()
            assert all(ticket_url not in payload for payload in events)
    finally:
        asyncio.run(app.state.previews.stop(preview_id, "test_cleanup"))
