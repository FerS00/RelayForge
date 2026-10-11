import asyncio
import json
import subprocess
import time

from relayforge.adapters.base import NormalizedEvent


class RecordingChat:
    def __init__(self, action=None, delay=0.0):
        self.action, self.delay = action, delay
        self.contexts, self.prompts = [], []

    async def chat(self, context, prompt):
        self.contexts.append(context)
        self.prompts.append(prompt)
        await asyncio.sleep(self.delay)
        action = None if "Resultado de herramienta" in prompt else self.action
        text = json.dumps({"response": "ok", "action": action})
        yield NormalizedEvent("agent.message", "codex", context.step_id, {"text": text})
        yield NormalizedEvent("agent.exit", "codex", context.step_id, {"outcome": "ok"})


def _wait(client, identifier, predicate):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        result = client.get(f"/api/conversations/{identifier}/messages").json()
        if predicate(result):
            return result
        time.sleep(0.02)
    raise AssertionError(result)


def _send(client, identifier, key):
    response = client.post(
        f"/api/conversations/{identifier}/messages",
        json={"content": "Solicitud " + key},
        headers={"Idempotency-Key": key},
    )
    assert response.status_code == 202


def _patch(client, identifier, body):
    return client.patch(f"/api/conversations/{identifier}/settings", json=body)


def _idle(data):
    return data["active_step"] is None and all(turn["status"] != "queued" for turn in data["turns"])


def test_settings_api_validates_version_effort_and_tools(client, app):
    app.state.chat._effort_catalog = (time.monotonic() + 3600, {"gpt-small": ("low", "medium")})
    created = client.post("/api/conversations", json={"agent": "codex", "model": "gpt-small"}).json()
    assert created["effort"] == "" and created["effective_effort"] == "medium"
    assert created["supported_efforts"] == ["low", "medium"] and created["settings_version"] == 0
    assert created["tools"]["write_files"] is True and created["tools"]["web_search"] is False
    identifier = created["id"]
    assert _patch(client, identifier, {"effort": "low", "settings_version": 5}).status_code == 409
    unsupported = _patch(client, identifier, {"effort": "max", "settings_version": 0})
    assert unsupported.status_code == 422
    assert unsupported.json()["error"]["code"] == "effort_unsupported"
    assert unsupported.json()["error"]["details"]["supported"] == ["low", "medium"]
    assert _patch(client, identifier, {"effort": "ultra", "settings_version": 0}).status_code == 422
    assert _patch(client, identifier, {"tools": {"shell": True}, "settings_version": 0}).status_code == 422
    dependency = _patch(
        client, identifier, {"tools": {"git_local": False, "remote_delivery": True}, "settings_version": 0}
    )
    assert dependency.json()["error"]["code"] == "tool_dependency"
    assert _patch(client, "missing", {"effort": "low", "settings_version": 0}).status_code == 404
    updated = _patch(
        client, identifier, {"effort": "low", "tools": {"web_search": True}, "settings_version": 0}
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["effort"] == "low" and body["tools"]["web_search"] is True and body["settings_version"] == 1
    without_csrf = client.patch(
        f"/api/conversations/{identifier}/settings",
        json={"effort": "medium", "settings_version": 1},
        headers={"X-CSRF-Token": "wrong"},
    )
    assert without_csrf.status_code == 403
    with app.state.engine.connect() as connection:
        kinds = [
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT type FROM events WHERE conversation_id = ?", (identifier,)
            )
        ]
    assert "conversation.settings" in kinds


def test_change_applies_from_next_turn_without_altering_running_turn(client, app):
    provider = RecordingChat(delay=0.6)
    app.state.chat.orchestrators["codex"] = provider
    identifier = client.post("/api/conversations", json={"agent": "codex"}).json()["id"]
    assert _patch(client, identifier, {"effort": "high", "settings_version": 0}).status_code == 200
    _send(client, identifier, "first")
    _wait(client, identifier, lambda data: data["active_step"] is not None)
    changed = _patch(
        client, identifier, {"effort": "low", "tools": {"web_search": True}, "settings_version": 1}
    )
    assert changed.status_code == 200
    data = _wait(client, identifier, _idle)
    assert provider.contexts[0].effort == "high" and provider.contexts[0].web_search is False
    assert data["turns"][0]["effort"] == "high"
    _send(client, identifier, "second")
    data = _wait(client, identifier, lambda result: len(result["turns"]) == 2 and _idle(result))
    assert provider.contexts[1].effort == "low" and provider.contexts[1].web_search is True
    assert data["turns"][1]["effort"] == "low"


def test_disabled_tool_is_rejected_in_core_and_returned_to_agent(client, app):
    provider = RecordingChat({"kind": "write_file", "path": "note.txt", "content": "FARO"})
    app.state.chat.orchestrators["codex"] = provider
    identifier = client.post("/api/conversations", json={"agent": "codex"}).json()["id"]
    disabled = _patch(client, identifier, {"tools": {"write_files": False}, "settings_version": 0})
    assert disabled.status_code == 200
    _send(client, identifier, "write")
    data = _wait(client, identifier, lambda result: len(result["turns"]) >= 2 and _idle(result))
    action = data["actions"][0]
    assert action["status"] == "rejected" and action["result"]["error"] == "tool_disabled:write_files"
    assert not (app.state.settings.workspace_dir / "note.txt").exists()
    active_tools = provider.prompts[0].split("Herramientas activas:", 1)[1].split(". ", 1)[0]
    assert "write_file" not in active_tools and "native_task" in active_tools
    assert "tool_disabled:write_files" in provider.prompts[1]
    decision = client.post(
        f"/api/conversations/{identifier}/actions/{action['id']}/decision",
        json={
            "version": action["version"],
            "operation_hash": action["operation_hash"],
            "decision": "approve",
        },
        headers={"Idempotency-Key": "approve-disabled"},
    )
    assert decision.status_code == 409


def test_remote_delivery_keeps_plan_approval_and_independent_review(client, app, monkeypatch):
    calls = []

    def create_job(*args, **kwargs):
        calls.append(kwargs)
        return {"id": "job-x", "status": "QUEUED"}, False

    monkeypatch.setattr(app.state.jobs, "create_job", create_job)
    repo = app.state.settings.projects_root / "repo"
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.test",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "init",
        ],
        check=True,
    )
    repository = app.state.repositories.register("repo", str(repo))
    provider = RecordingChat(
        {"kind": "development_job", "repository_id": repository["id"], "request": "Cambia X"}
    )
    app.state.chat.orchestrators["codex"] = provider
    identifier = client.post("/api/conversations", json={"agent": "codex"}).json()["id"]
    _send(client, identifier, "review")
    _wait(client, identifier, lambda result: len(result["turns"]) >= 2 and _idle(result))
    tools = dict.fromkeys(
        ("write_files", "commands", "git_local", "preview", "web_search", "remote_delivery"), True
    )
    assert _patch(client, identifier, {"tools": tools, "settings_version": 0}).status_code == 200
    _send(client, identifier, "deliver")
    _wait(client, identifier, lambda result: len(result["turns"]) >= 4 and _idle(result))
    assert [call["review_only"] for call in calls] == [True, False]
    assert all(call["require_plan_approval"] is True and call["planning_agent"] == "codex" for call in calls)
