from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient


def test_agent_secrets_are_redacted_from_messages_events_and_process_logs(
    client: TestClient, app, monkeypatch
) -> None:
    marker = "synthetic-stream-secret"
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "secret_output")
    conversation = client.post("/api/conversations", json={}).json()
    sent = client.post(
        f"/api/conversations/{conversation['id']}/messages",
        json={"content": "password=synthetic-user-secret"},
        headers={"Idempotency-Key": "redaction-chat"},
    )
    assert sent.status_code == 202
    assert sent.json()["message"]["content"] == "password=[REDACTED]"

    deadline = time.monotonic() + 8
    response = client.get(f"/api/conversations/{conversation['id']}/messages")
    while time.monotonic() < deadline:
        messages = response.json()["messages"]
        if any(
            message["content"] == "password=[REDACTED]"
            for message in messages
            if message["role"] == "orchestrator"
        ):
            break
        time.sleep(0.05)
        response = client.get(f"/api/conversations/{conversation['id']}/messages")

    assert response.status_code == 200
    assert marker not in json.dumps(response.json())
    with app.state.engine.connect() as connection:
        raw_events = " ".join(row[0] for row in connection.exec_driver_sql("SELECT payload_json FROM events"))
        raw_messages = " ".join(row[0] for row in connection.exec_driver_sql("SELECT content FROM messages"))
    assert marker not in raw_events + raw_messages

    data_root = app.state.settings.home / "data"
    log_contents = "".join(
        path.read_text(encoding="utf-8", errors="replace") for path in data_root.rglob("*") if path.is_file()
    )
    assert marker not in log_contents
