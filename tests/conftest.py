from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from relayforge.adapters.base import AuditResult
from relayforge.api.app import create_app
from relayforge.settings import Settings


class FakeAuditAdapter:
    name = "fake-audit"

    def __init__(self) -> None:
        self.profiles: list[str] = []

    async def audit(
        self, worktree, changed_paths, commands, iteration, diff_text="", profile="default"
    ) -> AuditResult:
        self.profiles.append(profile)
        return AuditResult("APPROVED", "La fixture no encontró hallazgos.", (), {}, {})


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def fake_launcher(tmp_path: Path) -> Path:
    launcher = tmp_path / "fake-agent.cmd"
    fake = ROOT / "tests" / "fakes" / "fake_agent.py"
    launcher.write_text(f'@echo off\r\n"{sys.executable}" -X utf8 "{fake}" %*\r\n', encoding="utf-8")
    return launcher


@pytest.fixture
def fake_codex_launcher(tmp_path: Path) -> Path:
    launcher = tmp_path / "fake-codex.cmd"
    fake = ROOT / "tests" / "fakes" / "fake_codex.py"
    launcher.write_text(f'@echo off\r\n"{sys.executable}" -X utf8 "{fake}" %*\r\n', encoding="utf-8")
    return launcher


@pytest.fixture
def app(tmp_path: Path, fake_launcher: Path, fake_codex_launcher: Path):
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
        projects_root=tmp_path / "projects",
        claude_executable=str(fake_launcher),
        claude_model="",
        codex_executable=str(fake_codex_launcher),
        allowed_tailscale_logins=("owner@example.test",),
        allowed_hosts=("relayforge.example.test",),
    )
    application = create_app(
        settings, db_path=tmp_path / "relayforge.db", web_dist=web_dist, auditor=FakeAuditAdapter()
    )
    application.state.settings = settings
    application.state.db_path = tmp_path / "relayforge.db"
    application.state.web_dist = web_dist
    return application


@pytest.fixture
def client(app, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "ok")
    with TestClient(
        app,
        base_url="https://localhost",
        headers={
            "Host": "localhost",
            "Origin": "https://localhost",
            "Tailscale-User-Login": "owner@example.test",
        },
    ) as test_client:
        csrf = test_client.get("/api/auth/csrf").json()["csrf_token"]
        test_client.headers.update({"X-CSRF-Token": csrf})
        pairing_code = app.state.auth.issue_pairing_code()
        paired = test_client.post("/api/auth/pair", json={"code": pairing_code})
        assert paired.status_code == 200
        app.state.test_session_token = test_client.cookies.get("rf_session")
        app.state.test_csrf_token = csrf
        yield test_client
