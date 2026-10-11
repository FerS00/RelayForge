from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from relayforge.api.app import create_app


def wait_turn(app) -> None:
    deadline = time.monotonic() + 8
    while app.state.chat.active and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not app.state.chat.active


def test_codex_chat_persists_provider_thread_and_resumes_after_reload(client, app) -> None:
    created = client.post("/api/conversations", json={"agent": "codex", "model": "gpt-6-luna"})
    assert created.status_code == 201
    row = created.json()
    assert row["agent"] == "codex" and row["model"] == "gpt-6-luna"
    assert row["runtime"] == "windows-native" and row["capabilities"][:4] == [
        "chat",
        "evidence",
        "actions",
        "deliverables",
    ]
    url = f"/api/conversations/{row['id']}/messages"
    assert client.post(url, json={"content": "hola"}, headers={"Idempotency-Key": "one"}).status_code == 202
    wait_turn(app)
    with app.state.engine.connect() as connection:
        stored = connection.exec_driver_sql(
            "SELECT orchestrator, model, session_id, session_established FROM conversations WHERE id=?",
            (row["id"],),
        ).one()
        assert tuple(stored) == ("codex", "gpt-6-luna", "fake-chat-thread", 1)
    assert client.get(url).json()["messages"][-1]["content"] == "Hola desde Codex"
    reloaded = create_app(app.state.settings, db_path=app.state.db_path, web_dist=app.state.web_dist)
    with TestClient(reloaded, base_url="https://localhost", headers=dict(client.headers)) as resumed:
        resumed.cookies.update(client.cookies)
        assert (
            resumed.post(url, json={"content": "continua"}, headers={"Idempotency-Key": "two"}).status_code
            == 202
        )
        wait_turn(reloaded)
        assert resumed.get(url).json()["messages"][-1]["content"] == "Contexto conservado"
        assert (
            resumed.post(url, json={"content": "otro"}, headers={"Idempotency-Key": "two"}).status_code == 200
        )
    with app.state.engine.connect() as connection:
        events = connection.exec_driver_sql(
            "SELECT actor, payload_json FROM events WHERE conversation_id=? AND type='step.finished'",
            (row["id"],),
        ).all()
    assert len(events) == 2
    assert all(json.loads(e[1])["data"]["agent"] == "codex" for e in events)
    assert not list(app.state.settings.workspace_dir.iterdir())


def test_conversation_rejects_invalid_agent_model(client) -> None:
    for body in ({"agent": "antigravity"}, {"agent": "unknown"}, {"model": "bad model!"}):
        assert client.post("/api/conversations", json=body).status_code == 422


def test_codex_chat_reports_missing_cli(client, app) -> None:
    from relayforge.adapters.codex.adapter import CodexAdapter

    app.state.chat.orchestrators["codex"].adapter = CodexAdapter("missing-chat-cli.exe")
    identifier = client.post("/api/conversations", json={"agent": "codex"}).json()["id"]
    url = f"/api/conversations/{identifier}/messages"
    client.post(url, json={"content": "hola"}, headers={"Idempotency-Key": "missing"})
    wait_turn(app)
    result = client.get(url).json()["messages"][-1]
    assert result["status"] == "error"
    assert "Codex" in result["content"] and "FileNotFoundError" in result["content"]


def test_codex_chat_timeout_releases_turn(client, app, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CODEX_CHAT_SCENARIO", "stall")
    adapter = app.state.chat.orchestrators["codex"]
    adapter.timeout_seconds = 0.1
    identifier = client.post("/api/conversations", json={"agent": "codex"}).json()["id"]
    url = f"/api/conversations/{identifier}/messages"
    client.post(url, json={"content": "hola"}, headers={"Idempotency-Key": "timeout"})
    wait_turn(app)
    assert "chat_timeout" in client.get(url).json()["messages"][-1]["content"]
    assert not app.state.supervisor._runs
    monkeypatch.delenv("FAKE_CODEX_CHAT_SCENARIO")
    adapter.timeout_seconds = 10
    client.post(url, json={"content": "continua"}, headers={"Idempotency-Key": "next"})
    wait_turn(app)
    assert client.get(url).json()["messages"][-1]["status"] == "complete"


def test_codex_auth_failure_is_classified(client, app, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CODEX_CHAT_SCENARIO", "auth")
    identifier = client.post("/api/conversations", json={"agent": "codex"}).json()["id"]
    url = f"/api/conversations/{identifier}/messages"
    client.post(url, json={"content": "hola"}, headers={"Idempotency-Key": "auth"})
    wait_turn(app)
    result = client.get(url).json()["messages"][-1]
    assert result["status"] == "error" and "auth_required" in result["content"]
