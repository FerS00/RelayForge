from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.request import urlopen

import psutil
import pytest
from sqlalchemy import select

from relayforge.core.previews import PreviewError
from relayforge.db.models import Job, Preview, utc_now

FAKE_SERVER = Path(__file__).resolve().parents[1] / "fakes" / "fake_preview_server.py"


def _conversation(app) -> tuple[str, Path]:
    app.state.previews.set_gateway_state(True)
    row = app.state.chat.create_conversation("codex")
    return row["id"], Path(app.state.settings.workspace_dir)


def _manifest(directory: Path, argv: list[str]) -> None:
    (directory / "relayforge-preview.json").write_text(
        json.dumps({"argv": argv, "ready_path": "/"}), encoding="utf-8"
    )


def _row(app, preview_id: str) -> Preview:
    with app.state.previews.sessions() as session:
        row = session.get(Preview, preview_id)
        assert row is not None
        return row


def test_command_preview_runs_without_shell_and_stop_kills_descendants(app) -> None:
    conversation_id, workspace = _conversation(app)
    _manifest(workspace, ["python", str(FAKE_SERVER), "--spawn-child"])
    result = asyncio.run(app.state.previews.start(conversation_id, "workspace", "", "action-1"))
    preview_id = str(result["preview_id"])
    preview = _row(app, preview_id)
    assert result == {
        "preview_id": preview_id,
        "status": "running",
        "kind": "command",
        "url_hint": "abre el panel Entregables",
    }
    assert preview.pid is not None and preview.pid_create_time is not None
    assert preview.port is not None
    with urlopen(f"http://127.0.0.1:{preview.port}/__pid", timeout=3) as response:
        identities = json.loads(response.read())
    child_pid = int(identities["child_pid"])
    try:
        stopped = asyncio.run(app.state.previews.stop(preview_id, "user"))
        assert stopped["status"] == "stopped"
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and (
            psutil.pid_exists(preview.pid) or psutil.pid_exists(child_pid)
        ):
            time.sleep(0.05)
        assert not psutil.pid_exists(preview.pid)
        assert not psutil.pid_exists(child_pid)
    finally:
        asyncio.run(app.state.previews.shutdown())


def test_static_missing_index_and_missing_command_fail_with_codes(
    app, monkeypatch: pytest.MonkeyPatch
) -> None:
    conversation_id, workspace = _conversation(app)
    with pytest.raises(PreviewError, match="preview_index_missing"):
        asyncio.run(app.state.previews.start(conversation_id, "workspace", "", None))
    with app.state.previews.sessions() as session:
        missing_index = session.scalar(select(Preview).where(Preview.error_code == "preview_index_missing"))
        assert missing_index is not None and missing_index.status == "failed"

    _manifest(workspace, ["python", str(FAKE_SERVER)])
    monkeypatch.setattr("relayforge.core.previews.shutil.which", lambda command: None)
    with pytest.raises(PreviewError, match="preview_command_not_found"):
        asyncio.run(app.state.previews.start(conversation_id, "workspace", "", None))
    with app.state.previews.sessions() as session:
        absent_command = session.scalar(
            select(Preview).where(Preview.error_code == "preview_command_not_found")
        )
        assert absent_command is not None and absent_command.status == "failed"


def test_first_available_port_is_used_and_exhaustion_is_reported(app) -> None:
    conversation_id, workspace = _conversation(app)
    _manifest(workspace, ["python", str(FAKE_SERVER)])
    occupied = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        occupied.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    occupied.bind(("127.0.0.1", 0))
    first = occupied.getsockname()[1]
    if first >= 65535 or first in {app.state.settings.port, app.state.settings.preview_gateway_port}:
        occupied.close()
        pytest.skip("No hay dos puertos consecutivos disponibles para esta prueba.")
    second_probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        second_probe.bind(("127.0.0.1", first + 1))
    except OSError:
        occupied.close()
        second_probe.close()
        pytest.skip("No hay dos puertos consecutivos disponibles para esta prueba.")
    second_probe.close()
    occupied.listen()
    app.state.previews.settings = app.state.settings.model_copy(
        update={"preview_port_range": (first, first + 1)}
    )
    try:
        started = asyncio.run(app.state.previews.start(conversation_id, "workspace", "", None))
        assert _row(app, str(started["preview_id"])).port == first + 1
        asyncio.run(app.state.previews.stop(str(started["preview_id"]), "user"))

        app.state.previews.settings = app.state.settings.model_copy(
            update={"preview_port_range": (first, first)}
        )
        with pytest.raises(PreviewError, match="preview_ports_exhausted"):
            asyncio.run(app.state.previews.start(conversation_id, "workspace", "", None))
    finally:
        occupied.close()
        asyncio.run(app.state.previews.shutdown())


def test_process_exit_and_start_timeout_fail_without_success(app, monkeypatch: pytest.MonkeyPatch) -> None:
    conversation_id, workspace = _conversation(app)
    _manifest(workspace, ["python", "-c", "import sys; sys.exit(0)"])
    with pytest.raises(PreviewError, match="preview_process_exited"):
        asyncio.run(app.state.previews.start(conversation_id, "workspace", "", None))

    monkeypatch.setattr("relayforge.core.previews._START_TIMEOUT_SECONDS", 0.25)
    _manifest(workspace, ["python", "-c", "import time; time.sleep(60)"])
    with pytest.raises(PreviewError, match="preview_start_timeout"):
        asyncio.run(app.state.previews.start(conversation_id, "workspace", "", None))
    with app.state.previews.sessions() as session:
        failed = list(session.scalars(select(Preview).where(Preview.conversation_id == conversation_id)))
    assert {row.error_code for row in failed} >= {"preview_process_exited", "preview_start_timeout"}
    assert all(row.status == "failed" for row in failed)
    asyncio.run(app.state.previews.shutdown())


def test_startup_interrupts_matching_process_identity(app) -> None:
    conversation_id, workspace = _conversation(app)
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False,
    )
    created = psutil.Process(process.pid).create_time()
    with app.state.previews.sessions.begin() as session:
        session.add(
            Preview(
                id="preview-restart",
                conversation_id=conversation_id,
                root_path=str(workspace),
                kind="command",
                argv_json="[]",
                port=8900,
                pid=process.pid,
                pid_create_time=created,
                status="running",
                last_access_at=utc_now(),
                created_at=utc_now(),
                version=0,
            )
        )

    asyncio.run(app.state.previews.startup())

    assert _row(app, "preview-restart").status == "interrupted"
    assert not psutil.pid_exists(process.pid)


def test_idle_timeout_and_job_cancellation_stop_previews(app) -> None:
    conversation_id, workspace = _conversation(app)
    (workspace / "index.html").write_text("static", encoding="utf-8")
    app.state.previews.settings = app.state.settings.model_copy(update={"preview_idle_seconds": 60})
    idle = asyncio.run(app.state.previews.start(conversation_id, "workspace", "", None))
    old_access = (datetime.now(UTC) - timedelta(minutes=2)).isoformat()
    with app.state.previews.sessions.begin() as session:
        session.get(Preview, str(idle["preview_id"])).last_access_at = old_access
    asyncio.run(app.state.previews.monitor_once())
    idle_row = _row(app, str(idle["preview_id"]))
    assert idle_row.status == "stopped" and idle_row.error_code == "preview_idle_timeout"

    job, _ = app.state.jobs.create_job(
        "Preview job", "Request", "preview-job", conversation_id=conversation_id
    )
    worktree = workspace / "job-worktree"
    worktree.mkdir()
    with app.state.previews.sessions.begin() as session:
        session.get(Job, job["id"]).worktree_path = str(worktree)
    (worktree / "index.html").write_text("job output", encoding="utf-8")
    linked = asyncio.run(app.state.previews.start(conversation_id, f"job:{job['id']}", "", None))
    with app.state.previews.sessions.begin() as session:
        session.get(Job, job["id"]).status = "CANCELLED"
    asyncio.run(app.state.previews.monitor_once())
    linked_row = _row(app, str(linked["preview_id"]))
    assert linked_row.status == "stopped"
    asyncio.run(app.state.previews.shutdown())
