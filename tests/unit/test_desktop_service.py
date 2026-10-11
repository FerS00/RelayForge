import asyncio
from pathlib import Path

import pytest
from tests.fakes.fake_desktop_worker import FakeDesktopWorker

from relayforge.desktop.service import DesktopError, DesktopService


@pytest.fixture
def desktop_env(app, tmp_path: Path):
    allowed_dir = tmp_path / "desktop-files"
    allowed_dir.mkdir()
    fake_exe = tmp_path / "notepad.exe"
    fake_exe.write_text("fake binary")
    settings = app.state.settings.model_copy(
        update={
            "desktop_allowed_dirs": (allowed_dir,),
            "desktop_apps": {"notepad": fake_exe},
        }
    )
    app.state.settings = settings
    worker = FakeDesktopWorker()
    service = DesktopService(app.state.chat.sessions, worker, settings, app.state.attachments)
    return service, worker, allowed_dir


def test_desktop_service_lifecycle(app, desktop_env):
    service, worker, allowed_dir = desktop_env
    cid = app.state.chat.create_conversation("codex")["id"]

    # 1. Launch
    launched = asyncio.run(service.launch(cid, "act-1", "notepad"))
    assert launched["status"] == "open"
    target_id = launched["target_id"]

    open_targets = service.list_open(cid)
    assert len(open_targets) == 1
    assert open_targets[0]["target_id"] == target_id

    # 2. Inspect
    inspected = asyncio.run(service.perform(cid, target_id, "desktop_inspect", {"depth": 2, "limit": 50}))
    assert "tree" in inspected

    # 3. Type text
    typed = asyncio.run(service.perform(cid, target_id, "desktop_type", {"text": "Hello Desktop"}))
    assert typed["typed_chars"] == 13

    # 4. Keys
    keys = asyncio.run(service.perform(cid, target_id, "desktop_keys", {"chord": "ctrl+s"}))
    assert keys["chord"] == "ctrl+s"

    # 5. Capture creates attachment
    captured = asyncio.run(service.perform(cid, target_id, "desktop_capture", {}))
    assert "attachment_id" in captured

    # 6. Close
    closed = asyncio.run(service.perform(cid, target_id, "desktop_close", {}))
    assert closed["operation"] == "close"
    assert len(service.list_open(cid)) == 0


def test_desktop_service_unavailable_and_elevated(app, tmp_path: Path):
    settings = app.state.settings
    worker = FakeDesktopWorker(interactive=False)
    service = DesktopService(app.state.chat.sessions, worker, settings, app.state.attachments)
    cid = "cid-1"

    with pytest.raises(DesktopError, match="desktop_unavailable"):
        asyncio.run(service.launch(cid, "act-1", "notepad"))

    worker_elevated = FakeDesktopWorker(elevated=True)
    service_elevated = DesktopService(
        app.state.chat.sessions, worker_elevated, settings, app.state.attachments
    )
    with pytest.raises(DesktopError, match="runtime_elevated"):
        asyncio.run(service_elevated.launch(cid, "act-1", "notepad"))


def test_desktop_service_close_targets_for_conversation(app, desktop_env):
    service, worker, allowed_dir = desktop_env
    cid = app.state.chat.create_conversation("codex")["id"]
    asyncio.run(service.launch(cid, "act-1", "notepad"))
    assert len(service.list_open(cid)) == 1

    asyncio.run(service.close_targets_for_conversation(cid))
    assert len(service.list_open(cid)) == 0
