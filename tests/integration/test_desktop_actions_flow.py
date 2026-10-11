import asyncio
import json
import time
from pathlib import Path

from tests.fakes.fake_desktop_worker import FakeDesktopWorker

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


def send(client, identifier, key, content="Solicitud desktop"):
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


def test_desktop_launch_requires_exact_approval_and_inspect_runs(client, app, tmp_path: Path):
    fake_exe = tmp_path / "notepad.exe"
    fake_exe.write_text("fake binary")
    app.state.settings = app.state.settings.model_copy(update={"desktop_apps": {"notepad": fake_exe}})
    worker = FakeDesktopWorker()
    from relayforge.desktop.service import DesktopService

    app.state.desktop = DesktopService(
        app.state.chat.sessions, worker, app.state.settings, app.state.attachments
    )
    app.state.actions.desktop = app.state.desktop
    app.state.chat.desktop = app.state.desktop

    provider = ScriptedChat({"kind": "desktop_launch", "path": "notepad"})
    app.state.chat.orchestrators["codex"] = provider

    identifier = client.post("/api/conversations", json={"agent": "codex"}).json()["id"]
    send(client, identifier, "req-launch")

    data = wait(client, identifier, lambda d: bool(d["actions"]) and d["active_step"] is None)
    action = data["actions"][0]
    assert action["status"] == "pending"

    # Approve launch
    res = decide(client, identifier, action, "dec-launch")
    assert res.status_code == 200

    data = wait(
        client,
        identifier,
        lambda d: d["actions"][0]["status"] == "complete" and len(d["turns"]) == 2 and not d["active_step"],
    )
    target_id = data["actions"][0]["result"]["target_id"]
    assert target_id
    # The agent must be told which apps exist, where it may save and which windows are open.
    assert "apps registradas: notepad" in provider.calls[0]
    assert str(app.state.desktop.allowed_dirs()[0]) in provider.calls[0]
    assert target_id in provider.calls[-1]

    # Now inspect (which should be immediate as it has no dangerous path)
    provider_inspect = ScriptedChat({"kind": "desktop_inspect", "path": target_id, "request": '{"depth": 2}'})
    app.state.chat.orchestrators["codex"] = provider_inspect
    send(client, identifier, "req-inspect")

    data = wait(
        client,
        identifier,
        lambda d: (
            len(d["actions"]) == 2
            and d["actions"][1]["status"] == "complete"
            and len(d["turns"]) == 4
            and not d["active_step"]
        ),
    )
    assert "tree" in data["actions"][1]["result"]

    # Menu commands run immediately on the verified target, without foreground.
    provider_menu = ScriptedChat(
        {"kind": "desktop_menu", "path": target_id, "request": '{"path": ["Archivo", "Guardar como..."]}'}
    )
    app.state.chat.orchestrators["codex"] = provider_menu
    send(client, identifier, "req-menu")
    data = wait(
        client,
        identifier,
        lambda d: len(d["actions"]) == 3 and d["actions"][2]["status"] == "complete" and not d["active_step"],
    )
    assert data["actions"][2]["result"]["command_id"] == 4
    assert worker.calls[-1]["op"] == "menu" and worker.calls[-1]["path"] == ["Archivo", "Guardar como..."]
