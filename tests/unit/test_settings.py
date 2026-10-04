from __future__ import annotations

from pathlib import Path

import pytest

from relayforge.settings import SettingsError, load_settings


def test_settings_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    default_workspace = tmp_path / "default"
    yaml_workspace = tmp_path / "yaml"
    env_workspace = tmp_path / "env"
    cli_workspace = tmp_path / "cli"
    for path in (default_workspace, yaml_workspace, env_workspace, cli_workspace):
        path.mkdir()
    home = tmp_path / "home"
    (home / "config").mkdir(parents=True)
    (home / "config/settings.yaml").write_text(
        f"workspace_dir: '{yaml_workspace}'\nport: 9000\n", encoding="utf-8"
    )
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("RELAYFORGE_HOME", str(home))
    monkeypatch.setenv("RELAYFORGE_WORKSPACE_DIR", str(env_workspace))
    monkeypatch.setenv("RELAYFORGE_PORT", "9001")
    from_environment = load_settings()
    assert from_environment.workspace_dir == env_workspace.resolve()
    assert from_environment.port == 9001
    monkeypatch.delenv("RELAYFORGE_WORKSPACE_DIR")
    monkeypatch.delenv("RELAYFORGE_PORT")
    from_yaml = load_settings()
    assert from_yaml.workspace_dir == yaml_workspace.resolve()
    assert from_yaml.port == 9000
    settings = load_settings(workspace_dir=cli_workspace, port=9002)
    assert settings.workspace_dir == cli_workspace.resolve()
    assert settings.port == 9002
    assert settings.home == home.resolve()


def test_settings_reject_bad_workspace_and_port(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    with pytest.raises(SettingsError):
        load_settings(workspace_dir=tmp_path / "missing")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(SettingsError):
        load_settings(workspace_dir=workspace, port=80)


def test_settings_reject_unsafe_claude_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(SettingsError, match="modelo de Claude"):
        load_settings(workspace_dir=workspace, claude_model="model&argument")
