from pathlib import Path

import pytest
from pydantic import ValidationError

from relayforge.core.actions import ActionError, ActionProposal, ChatReply, resource_path, snapshot


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        ".ssh/key.txt",
        ".codex/auth.json",
        "secret.pem",
        "file.txt:stream",
        "C:relative",
        "CON",
        "//host/share",
    ],
)
def test_protected_or_ambiguous_resource_is_rejected(tmp_path: Path, name: str):
    with pytest.raises(ActionError):
        resource_path(name, tmp_path)


def test_snapshot_checks_content_and_absent_parent(tmp_path: Path):
    target = tmp_path / "data.txt"
    original = snapshot(target)
    target.write_text("one", encoding="utf-8")
    first = snapshot(target)
    target.write_text("two", encoding="utf-8")
    assert first != snapshot(target) != original
    with pytest.raises(ActionError):
        snapshot(tmp_path / "missing" / "data.txt")


def test_closed_action_schema_rejects_terminal_and_extra_fields():
    for value in (
        {"kind": "shell", "request": "cmd"},
        {"kind": "read_file", "path": "file", "approve": True},
    ):
        with pytest.raises(ValidationError):
            ActionProposal.model_validate(value)
    with pytest.raises(ValidationError):
        ChatReply.model_validate({"response": "hola", "action": None, "approval": True})


def test_recovery_marks_uncertain_effects_interrupted_without_killing_reused_pid(app, monkeypatch):
    import asyncio
    import json

    from relayforge.db.models import ChatAction, ChatTurn, Message

    cid = app.state.chat.create_conversation()["id"]
    with app.state.chat.sessions.begin() as session:
        session.add(
            Message(
                id="m-recovery",
                conversation_id=cid,
                role="user",
                content="Request",
                step_id="t-recovery",
                status="complete",
            )
        )
        session.flush()
        session.add(
            ChatTurn(
                id="t-recovery",
                conversation_id=cid,
                message_id="m-recovery",
                agent="codex",
                model="fixture",
                status="running",
                pid=4242,
                pid_create_time=1,
            )
        )
        session.flush()
        session.add(
            ChatAction(
                id="a-recovery",
                conversation_id=cid,
                turn_id="t-recovery",
                kind="write_file",
                payload_json=json.dumps({"path": "note.txt"}),
                resource_path=str(app.state.settings.workspace_dir / "note.txt"),
                operation_hash="a" * 64,
                snapshot="absent",
                status="running",
                pid=4242,
                pid_create_time=1,
            )
        )
    killed = []

    class ReusedProcess:
        def __init__(self, pid):
            self.pid = pid

        def create_time(self):
            return 2

        def kill(self):
            killed.append(self.pid)

    monkeypatch.setattr("psutil.Process", ReusedProcess)
    asyncio.run(app.state.chat.startup())
    with app.state.chat.sessions() as session:
        assert session.get(ChatTurn, "t-recovery").status == "interrupted"
        assert session.get(ChatAction, "a-recovery").status == "interrupted"
    assert not killed and not list(app.state.settings.workspace_dir.iterdir())


def test_preview_actions_are_immediate_or_require_an_exact_manifest_approval(app):
    import json

    from relayforge.db.models import ChatTurn, Message, Preview

    app.state.previews.set_gateway_state(True)
    conversation = app.state.chat.create_conversation("codex")
    cid = conversation["id"]
    workspace = app.state.settings.workspace_dir
    static_site = workspace / "static-site"
    static_site.mkdir()
    (static_site / "index.html").write_text("static", encoding="utf-8")
    with app.state.actions.sessions.begin() as session:
        session.add(
            Message(
                id="preview-action-message",
                conversation_id=cid,
                role="user",
                content="Preview this",
                step_id="preview-action-turn",
                status="complete",
            )
        )
        session.flush()
        session.add(
            ChatTurn(
                id="preview-action-turn",
                conversation_id=cid,
                message_id="preview-action-message",
                agent="codex",
                model="fixture",
                status="complete",
            )
        )

    static, immediate = app.state.actions.propose(
        "preview-action-turn",
        ActionProposal(kind="start_preview", path="static-site"),
    )
    assert immediate and static["status"] == "approved"

    manifest = static_site / "relayforge-preview.json"
    manifest.write_text(
        json.dumps({"argv": ["python", "-c", "import time; time.sleep(60)"], "ready_path": "/"}),
        encoding="utf-8",
    )
    command, immediate = app.state.actions.propose(
        "preview-action-turn",
        ActionProposal(kind="start_preview", path="static-site"),
    )
    assert not immediate and command["status"] == "pending"
    manifest.write_text(
        json.dumps({"argv": ["python", "-c", "print('changed')"], "ready_path": "/"}),
        encoding="utf-8",
    )
    with pytest.raises(ActionError, match="resource_snapshot_changed"):
        app.state.actions.decide(
            cid,
            command["id"],
            command["version"],
            command["operation_hash"],
            "approve",
            "preview-decision",
        )
    exact, immediate = app.state.actions.propose(
        "preview-action-turn",
        ActionProposal(kind="start_preview", path="static-site"),
    )
    approved = app.state.actions.decide(
        cid,
        exact["id"],
        exact["version"],
        exact["operation_hash"],
        "approve",
        "preview-exact-decision",
    )
    assert not immediate and approved["status"] == "approved"

    with app.state.actions.sessions.begin() as session:
        session.add(
            Preview(
                id="preview-to-stop",
                conversation_id=cid,
                root_path=str(static_site),
                kind="static",
                argv_json="[]",
                status="running",
                last_access_at="t1",
                created_at="t1",
                version=0,
            )
        )
    stop, immediate = app.state.actions.propose(
        "preview-action-turn",
        ActionProposal(kind="stop_preview", request="preview-to-stop"),
    )
    assert immediate and stop["status"] == "approved"
    with pytest.raises(ActionError, match="preview_not_found"):
        app.state.actions.propose(
            "preview-action-turn",
            ActionProposal(kind="stop_preview", request="missing-preview"),
        )
