from __future__ import annotations

import os
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


def test_settings_fail_closed_for_non_loopback_bind_and_wildcard_allowlists(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(SettingsError, match="127.0.0.1"):
        load_settings(workspace_dir=workspace, bind="0.0.0.0")
    with pytest.raises(SettingsError, match="valores exactos"):
        load_settings(workspace_dir=workspace, allowed_hosts="*.example.test")


def test_settings_normalize_exact_allowlists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = load_settings(
        workspace_dir=workspace,
        allowed_tailscale_logins=" Owner@Example.Test,owner@example.test ",
        allowed_hosts="RelayForge.Example.Test",
    )
    assert settings.allowed_tailscale_logins == ("owner@example.test",)
    assert settings.allowed_hosts == ("relayforge.example.test",)


def test_settings_parse_json_allowlists_from_environment(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("RELAYFORGE_ALLOWED_TAILSCALE_LOGINS", '["Owner@Example.Test"]')
    monkeypatch.setenv("RELAYFORGE_ALLOWED_HOSTS", '["RelayForge.Example.Test"]')

    settings = load_settings(workspace_dir=workspace)

    assert settings.allowed_tailscale_logins == ("owner@example.test",)
    assert settings.allowed_hosts == ("relayforge.example.test",)


@pytest.mark.skipif(os.name != "nt", reason="El modo contenedor usa APIs Windows.")
def test_settings_accept_windows_container_with_exact_nat_gateway(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    settings = load_settings(
        workspace_dir=workspace,
        bind="0.0.0.0",
        container_mode=True,
        trusted_proxy_ip="172.30.0.1",
    )

    assert settings.bind == "0.0.0.0"
    assert settings.container_mode is True
    assert settings.trusted_proxy_ip == "172.30.0.1"


@pytest.mark.parametrize("proxy_ip", ["", "invalid", "127.0.0.1", "0.0.0.0", "224.0.0.1", "::1"])
@pytest.mark.skipif(os.name != "nt", reason="El modo contenedor usa APIs Windows.")
def test_settings_reject_container_proxy_unless_exact_ipv4_unicast(
    tmp_path: Path, monkeypatch, proxy_ip: str
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(SettingsError, match="TRUSTED_PROXY_IP"):
        load_settings(
            workspace_dir=workspace,
            bind="0.0.0.0",
            container_mode=True,
            trusted_proxy_ip=proxy_ip,
        )
