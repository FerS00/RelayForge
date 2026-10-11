import asyncio
import json
import time

from relayforge.adapters.base import NormalizedEvent


class ScriptedChat:
    def __init__(self, action, delay=0):
        self.action, self.delay, self.calls = action, delay, []

    async def chat(self, context, prompt):
        self.calls.append(prompt)
        await asyncio.sleep(self.delay)
        action = None if "Resultado de herramienta" in prompt else self.action
        text = json.dumps(
            {"response": "Resultado recibido" if action is None else "Acción propuesta", "action": action}
        )
        yield NormalizedEvent("agent.message", "codex", context.step_id, {"text": text})
        yield NormalizedEvent("agent.exit", "codex", context.step_id, {"outcome": "ok"})


def wait(client, identifier, predicate):
    url = f"/api/conversations/{identifier}/messages"
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        result = client.get(url).json()
        if predicate(result):
            return result
        time.sleep(0.02)
    raise AssertionError(result)


def send(client, identifier, key, content="Solicitud natural"):
    return client.post(
        f"/api/conversations/{identifier}/messages",
        json={"content": content},
        headers={"Idempotency-Key": key},
    )


def decide(client, identifier, action, key="decision", value="approve"):
    return client.post(
        f"/api/conversations/{identifier}/actions/{action['id']}/decision",
        json={"version": action["version"], "operation_hash": action["operation_hash"], "decision": value},
        headers={"Idempotency-Key": key},
    )


def test_write_requires_exact_decision_and_result_returns_to_agent(client, app):
    provider = ScriptedChat({"kind": "write_file", "path": "note.txt", "content": "FARO acción"})
    app.state.chat.orchestrators["codex"] = provider
    identifier = client.post("/api/conversations", json={"agent": "codex"}).json()["id"]
    send(client, identifier, "request")
    result = wait(client, identifier, lambda data: bool(data["actions"]) and data["active_step"] is None)
    action = result["actions"][0]
    path = app.state.settings.workspace_dir / "note.txt"
    assert not path.exists() and action["status"] == "pending"
    assert decide(client, "other", action).status_code == 404
    stale = {**action, "version": action["version"] + 1}
    assert decide(client, identifier, stale).status_code == 409
    assert decide(client, identifier, action).status_code == 200
    result = wait(
        client,
        identifier,
        lambda data: (
            data["actions"][0]["status"] == "complete"
            and len(data["turns"]) == 2
            and data["active_step"] is None
        ),
    )
    assert path.read_text(encoding="utf-8") == "FARO acción"
    assert len(provider.calls) == 2 and "written_bytes" in provider.calls[-1]
    assert result["messages"][-1]["content"] == "Resultado recibido"
    assert decide(client, identifier, action).status_code == 200
    assert len(client.get(f"/api/conversations/{identifier}/messages").json()["turns"]) == 2


def test_snapshot_change_rejects_write_and_listo_is_not_approval(client, app):
    path = app.state.settings.workspace_dir / "existing.txt"
    path.write_text("original", encoding="utf-8")
    app.state.chat.orchestrators["codex"] = ScriptedChat(
        {"kind": "write_file", "path": "existing.txt", "content": "changed"}
    )
    identifier = client.post("/api/conversations", json={"agent": "codex"}).json()["id"]
    send(client, identifier, "request")
    result = wait(client, identifier, lambda data: bool(data["actions"]) and data["active_step"] is None)
    action = result["actions"][0]
    send(client, identifier, "listo", "listo")
    wait(client, identifier, lambda data: len(data["turns"]) == 2 and data["active_step"] is None)
    assert path.read_text(encoding="utf-8") == "original"
    path.write_text("manual edit", encoding="utf-8")
    assert decide(client, identifier, action).status_code == 409
    assert path.read_text(encoding="utf-8") == "manual edit"


def test_local_read_executes_without_write_and_turns_queue(client, app):
    path = app.state.settings.workspace_dir / "readme.txt"
    path.write_text("FARO lectura", encoding="utf-8")
    provider = ScriptedChat({"kind": "read_file", "path": "readme.txt"}, delay=0.1)
    app.state.chat.orchestrators["codex"] = provider
    identifier = client.post("/api/conversations", json={"agent": "codex"}).json()["id"]
    assert send(client, identifier, "one").status_code == 202
    assert send(client, identifier, "two").status_code == 202
    result = wait(client, identifier, lambda data: len(data["turns"]) == 4 and data["active_step"] is None)
    assert len(result["actions"]) == 2
    assert all(action["status"] == "complete" for action in result["actions"])
    assert path.read_text(encoding="utf-8") == "FARO lectura"
    assert len(provider.calls) == 4
    with app.state.engine.connect() as connection:
        sequences = (
            connection.exec_driver_sql(
                "SELECT seq FROM events WHERE conversation_id=? ORDER BY seq", (identifier,)
            )
            .scalars()
            .all()
        )
    assert sequences == list(range(1, len(sequences) + 1))


def test_native_task_is_approved_scoped_and_has_result(client, app):
    root = app.state.settings.workspace_dir
    app.state.chat.orchestrators["codex"] = ScriptedChat(
        {"kind": "native_task", "path": str(root), "request": "Crea un texto de prueba"}
    )
    identifier = client.post("/api/conversations", json={"agent": "codex"}).json()["id"]
    send(client, identifier, "native-request")
    data = wait(client, identifier, lambda value: bool(value["actions"]) and value["active_step"] is None)
    action = data["actions"][0]
    assert not (root / "fake-native.txt").exists()
    assert decide(client, identifier, action).status_code == 200
    data = wait(
        client,
        identifier,
        lambda value: (
            value["actions"][0]["status"] == "complete"
            and len(value["turns"]) == 2
            and not value["active_step"]
        ),
    )
    assert (root / "fake-native.txt").read_text(encoding="utf-8") == "native fixture"
    assert data["actions"][0]["result"]["changed_paths"] == ["fake-native.txt"]


def test_queued_message_survives_app_reload_and_is_run_once(client, app):
    from fastapi.testclient import TestClient

    from relayforge.api.app import create_app

    app.state.chat.closing = True
    cid = client.post("/api/conversations", json={"agent": "codex"}).json()["id"]
    assert send(client, cid, "persist-queued").status_code == 202
    assert client.get(f"/api/conversations/{cid}/messages").json()["turns"][0]["status"] == "queued"
    reloaded = create_app(app.state.settings, db_path=app.state.db_path, web_dist=app.state.web_dist)
    with TestClient(reloaded, base_url="https://localhost", headers=dict(client.headers)) as resumed:
        resumed.cookies.update(client.cookies)
        data = wait(
            resumed, cid, lambda value: value["turns"][0]["status"] == "complete" and not value["active_step"]
        )
        assert len(data["turns"]) == 1 and len(data["messages"]) == 2
        assert send(resumed, cid, "persist-queued").status_code == 200
        assert len(resumed.get(f"/api/conversations/{cid}/messages").json()["turns"]) == 1


def test_write_into_new_folder_and_invalid_proposal_return_to_agent(client, app):
    provider = ScriptedChat({"kind": "write_file", "path": "site/index.html", "content": "<h1>FARO</h1>"})
    app.state.chat.orchestrators["codex"] = provider
    identifier = client.post("/api/conversations", json={"agent": "codex"}).json()["id"]
    send(client, identifier, "new-folder")
    result = wait(client, identifier, lambda data: bool(data["actions"]) and data["active_step"] is None)
    action = result["actions"][0]
    assert action["status"] == "pending"
    assert decide(client, identifier, action, "new-folder-decision").status_code == 200
    wait(client, identifier, lambda data: data["actions"][0]["status"] == "complete")
    assert (app.state.settings.workspace_dir / "site" / "index.html").read_text(
        encoding="utf-8"
    ) == "<h1>FARO</h1>"

    invalid = ScriptedChat({"kind": "read_file", "path": ".env"})
    app.state.chat.orchestrators["codex"] = invalid
    other = client.post("/api/conversations", json={"agent": "codex"}).json()["id"]
    send(client, other, "invalid-proposal")
    data = wait(client, other, lambda value: len(value["turns"]) >= 2 and value["active_step"] is None)
    assert not data["actions"]
    assert all(message["status"] != "error" for message in data["messages"])
    assert "resource_protected" in invalid.calls[1]


class CommentaryChat:
    def __init__(self, final):
        self.final = final

    async def chat(self, context, prompt):
        yield NormalizedEvent("agent.message", "codex", context.step_id, {"text": "Abriré el archivo."})
        if self.final is not None and "Resultado de herramienta" not in prompt:
            yield NormalizedEvent("agent.message", "codex", context.step_id, {"text": json.dumps(self.final)})
        elif self.final is not None:
            text = json.dumps({"response": "Hecho", "action": None})
            yield NormalizedEvent("agent.message", "codex", context.step_id, {"text": text})
        yield NormalizedEvent("agent.exit", "codex", context.step_id, {"outcome": "ok"})


def test_plain_commentary_before_structured_reply_is_kept_and_reply_runs(client, app):
    (app.state.settings.workspace_dir / "a.txt").write_text("FARO", encoding="utf-8")
    final = {"response": "Leo a.txt", "action": {"kind": "read_file", "path": "a.txt"}}
    app.state.chat.orchestrators["codex"] = CommentaryChat(final)
    identifier = client.post("/api/conversations", json={"agent": "codex"}).json()["id"]
    send(client, identifier, "commentary")
    data = wait(client, identifier, lambda value: len(value["turns"]) >= 2 and value["active_step"] is None)
    assert data["actions"][0]["status"] == "complete"
    texts = [message["content"] for message in data["messages"] if message["role"] == "orchestrator"]
    assert "Abriré el archivo." in texts and "Leo a.txt" in texts
    assert all(message["status"] != "error" for message in data["messages"])


def test_commentary_without_structured_reply_fails_clearly(client, app):
    app.state.chat.orchestrators["codex"] = CommentaryChat(None)
    identifier = client.post("/api/conversations", json={"agent": "codex"}).json()["id"]
    send(client, identifier, "no-structured")
    data = wait(client, identifier, lambda value: value["active_step"] is None and value["turns"])
    errors = [message["content"] for message in data["messages"] if message["status"] == "error"]
    assert errors and "structured_reply_missing" in errors[0]
