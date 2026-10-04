from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from relayforge.api.app import create_app
from relayforge.settings import Settings

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fake_launcher(tmp_path: Path) -> Path:
    launcher = tmp_path / "fake-agent.cmd"
    fake = ROOT / "tests" / "fakes" / "fake_agent.py"
    launcher.write_text(f'@echo off\r\n"{sys.executable}" -X utf8 "{fake}" %*\r\n', encoding="utf-8")
    return launcher


@pytest.fixture
def app(tmp_path: Path, fake_launcher: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    home = tmp_path / "home"
    web_dist = tmp_path / "dist"
    web_dist.mkdir()
    (web_dist / "index.html").write_text("<html></html>", encoding="utf-8")
    settings = Settings(
        workspace_dir=workspace,
        port=8787,
        home=home,
        claude_executable=str(fake_launcher),
        claude_model="",
    )
    application = create_app(settings, db_path=tmp_path / "relayforge.db", web_dist=web_dist)
    application.state.settings = settings
    application.state.db_path = tmp_path / "relayforge.db"
    application.state.web_dist = web_dist
    return application


@pytest.fixture
def client(app, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "ok")
    with TestClient(app, headers={"Host": "localhost"}) as test_client:
        yield test_client
