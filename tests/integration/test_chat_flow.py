from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from relayforge.adapters.claude.adapter import ClaudeAdapter
from relayforge.api.app import create_app


def test_chat_persists_turn_and_replays_idempotency(client: TestClient, app, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "blocks")
    created = client.post("/api/conversations", json={}).json()
    response = client.post(
        f"/api/conversations/{created['id']}/messages",
        json={"content": "hello"},
        headers={"Idempotency-Key": "key-1"},
    )
    assert response.status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and app.state.chat.active:
        time.sleep(0.02)
    messages = client.get(f"/api/conversations/{created['id']}/messages").json()["messages"]
    assert [message["role"] for message in messages] == ["user", "orchestrator"]
    assert messages[-1]["content"] == "visible answer"
    replay = client.post(
        f"/api/conversations/{created['id']}/messages",
        json={"content": "hello"},
        headers={"Idempotency-Key": "key-1"},
    )
    assert replay.status_code == 200
    with app.state.engine.connect() as connection:
        combined = " ".join(
            row[0] + " " + row[1]
            for row in connection.exec_driver_sql("SELECT content, '' FROM messages").all()
        )
        events = " ".join(
            row[0] for row in connection.exec_driver_sql("SELECT payload_json FROM events").all()
        )
        event_order = connection.exec_driver_sql(
            "SELECT seq, type FROM events WHERE conversation_id=? ORDER BY seq", (created["id"],)
        ).all()
    assert [row[0] for row in event_order] == list(range(1, len(event_order) + 1))
    assert event_order[0][1] == "step.started"
    for marker in (
        "FAKE_THINKING_MARKER",
        "FAKE_TOOL_MARKER",
        "FAKE_SKILL_MARKER",
        "FAKE_STDERR_MARKER",
        "FAKE_OTHER_MARKER",
    ):
        assert marker not in combined + events
    reloaded = create_app(
        app.state.settings,
        db_path=app.state.db_path,
        web_dist=app.state.web_dist,
    )
    assert reloaded.state.chat.get_conversation(created["id"])["id"] == created["id"]
    assert [item["content"] for item in reloaded.state.chat.list_messages(created["id"])["messages"]] == [
        "hello",
        "visible answer",
    ]
    reloaded.state.engine.dispose()


@pytest.mark.parametrize(
    ("scenario", "outcome"),
    [("error_result", "failed"), ("exit_nonzero", "failed"), ("no_result", "invalid_output")],
)
def test_failed_turn_is_persisted_and_conversation_accepts_next_message(
    client: TestClient, app, monkeypatch, scenario: str, outcome: str
) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", scenario)
    conversation = client.post("/api/conversations", json={}).json()
    endpoint = f"/api/conversations/{conversation['id']}/messages"
    response = client.post(
        endpoint,
        json={"content": "first"},
        headers={"Idempotency-Key": f"fail-{scenario}"},
    )
    assert response.status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and app.state.chat.active:
        time.sleep(0.02)
    messages = client.get(f"/api/conversations/{conversation['id']}/messages").json()["messages"]
    assert messages[-1]["role"] == "orchestrator" and messages[-1]["status"] == "error"
    with app.state.engine.connect() as connection:
        finishes = connection.exec_driver_sql(
            "SELECT payload_json FROM events WHERE type='step.finished'"
        ).all()
    assert any(f'"outcome":"{outcome}"' in row[0] for row in finishes)
    assert (
        client.post(
            endpoint,
            json={"content": "again"},
            headers={"Idempotency-Key": f"retry-{scenario}"},
        ).status_code
        == 202
    )


def test_active_turn_rejects_second_request_and_validation_errors(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "two_messages")
    conversation = client.post("/api/conversations", json={}).json()
    endpoint = f"/api/conversations/{conversation['id']}/messages"
    assert (
        client.post(endpoint, json={"content": "first"}, headers={"Idempotency-Key": "active-1"}).status_code
        == 202
    )
    assert (
        client.post(endpoint, json={"content": "second"}, headers={"Idempotency-Key": "active-2"}).status_code
        == 409
    )
    assert client.post(endpoint, json={"content": "missing"}).status_code == 400
    assert (
        client.post(endpoint, json={"content": "  "}, headers={"Idempotency-Key": "blank"}).status_code == 422
    )
    assert (
        client.post(
            endpoint,
            json={"content": "x" * 100_001},
            headers={"Idempotency-Key": "too-long"},
        ).status_code
        == 422
    )
    assert client.get("/api/conversations/missing").status_code == 404


def test_missing_agent_executable_finishes_as_start_failed(client: TestClient, app, tmp_path) -> None:
    app.state.chat.orchestrator.adapter = ClaudeAdapter(str(tmp_path / "missing-agent.exe"))
    conversation = client.post("/api/conversations", json={}).json()
    response = client.post(
        f"/api/conversations/{conversation['id']}/messages",
        json={"content": "start failure"},
        headers={"Idempotency-Key": "start-failed"},
    )
    assert response.status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and app.state.chat.active:
        time.sleep(0.02)
    assert (
        client.get(f"/api/conversations/{conversation['id']}/messages").json()["messages"][-1]["status"]
        == "error"
    )
    with app.state.engine.connect() as connection:
        finished = connection.exec_driver_sql(
            "SELECT payload_json FROM events WHERE type='step.finished'"
        ).all()
    assert any('"outcome":"start_failed"' in row[0] for row in finished)


def test_post_validation_and_host_security(client: TestClient):
    assert client.get("/", headers={"Host": "localhost"}).status_code == 200
    assert client.get("/", headers={"Host": "attacker.example"}).status_code == 400
    created = client.post("/api/conversations", json={}, headers={"Origin": "http://attacker.example"})
    assert created.status_code == 403
    created = client.post("/api/conversations", json={}).json()
    assert (
        client.post(
            f"/api/conversations/{created['id']}/messages", content="bad", headers={"Idempotency-Key": "x"}
        ).status_code
        == 415
    )
