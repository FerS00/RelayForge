import pytest
from fastapi.testclient import TestClient

from relayforge import cli
from relayforge.core.auth import AuthService


@pytest.mark.parametrize(
    ("peer", "forwarded", "expected"),
    [("127.0.0.1", "100.64.0.42", 200), ("100.64.0.43", "127.0.0.1", 403)],
)
def test_cli_preserves_proxy_peer_for_pairing(app, monkeypatch, tmp_path, peer, forwarded, expected):
    distribution = tmp_path / "web" / "dist"
    distribution.mkdir(parents=True)
    (distribution / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr(cli, "__file__", str(tmp_path / "src" / "relayforge" / "cli.py"))
    monkeypatch.setattr(cli, "load_settings", lambda **_: app.state.settings.model_copy(update={"port": 0}))
    monkeypatch.setattr(cli.shutil, "which", lambda _: "fake-agent")
    monkeypatch.setattr(cli, "create_app", lambda *args, **kwargs: app)

    def run(server, sockets):
        server.config.load()
        with TestClient(
            server.config.loaded_app,
            base_url="https://relayforge.example.test",
            client=(peer, 50000),
            headers={
                "Host": "relayforge.example.test",
                "Origin": "https://relayforge.example.test",
                "Tailscale-User-Login": "owner@example.test",
                "X-Forwarded-For": forwarded,
                "X-Forwarded-Proto": "https",
            },
        ) as client:
            csrf = client.get("/api/auth/csrf").json()["csrf_token"]
            code = app.state.auth.issue_pairing_code()
            paired = client.post("/api/auth/pair", json={"code": code}, headers={"X-CSRF-Token": csrf})
            assert paired.status_code == expected, paired.text
            if expected == 200:
                assert client.get("/api/auth/status").json() == {"authenticated": True}
                assert client.get("/api/agents").status_code == 200
            else:
                assert paired.json()["error"]["code"] == "identity_denied"

    monkeypatch.setattr(cli._RelayForgeServer, "run", run)
    assert cli.main(["serve"]) == 0


def _unpaired(app) -> TestClient:
    return TestClient(
        app,
        base_url="https://relayforge.example.test",
        headers={
            "Host": "relayforge.example.test",
            "Origin": "https://relayforge.example.test",
            "Tailscale-User-Login": "owner@example.test",
        },
    )


def test_pair_code_is_one_use_and_cookie_is_hardened(app) -> None:
    code = app.state.auth.issue_pairing_code()
    with _unpaired(app) as client:
        csrf = client.get("/api/auth/csrf").json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf}
        rejected = client.post("/api/auth/pair", json={"code": "x" * 24}, headers=headers)
        assert rejected.status_code == 403
        paired = client.post("/api/auth/pair", json={"code": code}, headers=headers)
        assert paired.status_code == 200
        cookie = paired.headers["set-cookie"].lower()
        assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
        assert client.get("/api/auth/status").json() == {"authenticated": True}
        assert client.post("/api/auth/pair", json={"code": code}, headers=headers).status_code == 403


def test_api_requires_pairing_and_identity_allowlist(app) -> None:
    with _unpaired(app) as client:
        assert client.get("/api/jobs").status_code == 401
        assert (
            client.get("/api/jobs", headers={"Tailscale-User-Login": "other@example.test"}).status_code == 401
        )


@pytest.mark.parametrize(("peer", "expected"), [("172.30.0.1", 200), ("172.30.0.2", 403)])
def test_container_pairing_trusts_only_exact_nat_gateway(app, peer, expected) -> None:
    settings = app.state.settings.model_copy(
        update={"container_mode": True, "trusted_proxy_ip": "172.30.0.1"}
    )
    app.state.settings = settings
    code = app.state.auth.issue_pairing_code()
    with TestClient(
        app,
        base_url="https://relayforge.example.test",
        client=(peer, 50000),
        headers={
            "Host": "relayforge.example.test",
            "Origin": "https://relayforge.example.test",
            "Tailscale-User-Login": "owner@example.test",
        },
    ) as client:
        csrf = client.get("/api/auth/csrf").json()["csrf_token"]
        response = client.post("/api/auth/pair", json={"code": code}, headers={"X-CSRF-Token": csrf})

    assert response.status_code == expected


def test_pairing_rejects_identity_outside_allowlist(app) -> None:
    code = app.state.auth.issue_pairing_code()
    with _unpaired(app) as client:
        csrf = client.get("/api/auth/csrf").json()["csrf_token"]
        response = client.post(
            "/api/auth/pair",
            json={"code": code},
            headers={"Tailscale-User-Login": "other@example.test", "X-CSRF-Token": csrf},
        )
        assert response.status_code == 403
        assert client.get("/api/auth/status").json() == {"authenticated": False}


def test_authenticated_mutations_require_origin_and_csrf(client) -> None:
    denied = client.post(
        "/api/jobs", json={"title": "x", "request_text": "y"}, headers={"X-CSRF-Token": "bad"}
    )
    assert denied.status_code == 403
    denied_origin = client.post(
        "/api/jobs", json={"title": "x", "request_text": "y"}, headers={"Origin": "https://evil.invalid"}
    )
    assert denied_origin.status_code == 403


def test_sse_requires_exact_origin(client) -> None:
    response = client.get(
        "/api/stream?conversation=conversation-none", headers={"Origin": "https://evil.invalid"}
    )
    assert response.status_code == 403


def test_sse_accepts_same_origin_eventsource_fetch_metadata(client) -> None:
    response = client.get(
        "/api/stream?conversation=conversation-none", headers={"Sec-Fetch-Site": "same-origin"}
    )
    assert response.status_code == 404


def test_sse_rejects_cross_site_fetch_metadata_without_origin(client) -> None:
    client.headers.pop("Origin")
    response = client.get(
        "/api/stream?conversation=conversation-none", headers={"Sec-Fetch-Site": "cross-site"}
    )
    assert response.status_code == 403


def test_logout_revokes_session(client) -> None:
    assert client.post("/api/auth/logout", json={}).status_code == 200
    assert client.get("/api/jobs").status_code == 401


def test_pairing_code_expires(monkeypatch, app) -> None:
    from datetime import UTC, datetime, timedelta

    import relayforge.core.auth as auth_module

    code = app.state.auth.issue_pairing_code()
    monkeypatch.setattr(auth_module, "_now", lambda: datetime.now(UTC) + timedelta(minutes=11))
    assert app.state.auth.pair(code, "owner@example.test") is None


def test_auth_service_does_not_persist_plaintext_pairing_code(app) -> None:
    code = AuthService(app.state.auth.sessions).issue_pairing_code()
    from sqlalchemy import text

    with app.state.engine.connect() as connection:
        assert connection.scalar(text("SELECT secret_hash FROM pairing_codes")) != code
