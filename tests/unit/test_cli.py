import json
import signal
import socket
import subprocess

import pytest

from relayforge import cli
from relayforge.cli import main
from relayforge.settings import Settings


def test_cli_reports_missing_workspace(monkeypatch, capsys) -> None:
    monkeypatch.setenv("LOCALAPPDATA", ".")
    monkeypatch.delenv("RELAYFORGE_WORKSPACE_DIR", raising=False)
    assert main(["serve"]) == 2
    assert "obligatorio" in capsys.readouterr().err


def test_cli_repo_add_registers_existing_repository(monkeypatch, capsys, tmp_path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main", str(repository)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@localhost",
            "commit",
            "--allow-empty",
            "-m",
            "init",
        ],
        check=True,
        capture_output=True,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(
        workspace_dir=workspace,
        port=8787,
        home=tmp_path / "home",
        projects_root=tmp_path / "projects",
        claude_executable="claude",
        codex_executable="codex",
    )
    monkeypatch.setattr(cli, "load_settings", lambda **_: settings)
    assert main(["repo", "add", "fixture", str(repository)]) == 0
    assert json.loads(capsys.readouterr().out)["repository"]["name"] == "fixture"


def test_cli_rejects_occupied_port_without_printing_url(monkeypatch, capsys, tmp_path) -> None:
    occupied = socket.socket()
    occupied.bind(("127.0.0.1", 0))
    occupied.listen()
    port = occupied.getsockname()[1]
    settings = Settings(
        workspace_dir=tmp_path,
        port=port,
        home=tmp_path / "home",
        projects_root=tmp_path / "projects",
        claude_executable="claude",
        codex_executable="codex",
    )
    monkeypatch.setattr(cli, "load_settings", lambda **_: settings)
    monkeypatch.setattr(cli.shutil, "which", lambda _: "claude.exe")
    try:
        assert main(["serve"]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.strip() == (
            f"El puerto {port} de 127.0.0.1 ya está en uso; usa --port o RELAYFORGE_PORT."
        )
    finally:
        occupied.close()


@pytest.mark.parametrize("signal_name", ["SIGINT", "SIGBREAK"])
def test_cli_returns_zero_after_shutdown_signal(monkeypatch, tmp_path, signal_name: str) -> None:
    shutdown_signal = getattr(signal, signal_name, None)
    if shutdown_signal is None:
        pytest.skip(f"{signal_name} no está disponible en esta plataforma.")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repository = tmp_path / "repo"
    distribution = repository / "web" / "dist"
    distribution.mkdir(parents=True)
    (distribution / "index.html").write_text("<html></html>", encoding="utf-8")
    settings = Settings(
        workspace_dir=workspace,
        port=0,
        home=tmp_path / "home",
        projects_root=tmp_path / "projects",
        claude_executable="claude",
        codex_executable="codex",
    )
    module_path = repository / "src" / "relayforge" / "cli.py"
    monkeypatch.setattr(cli, "__file__", str(module_path))
    monkeypatch.setattr(cli, "load_settings", lambda **_: settings)
    monkeypatch.setattr(cli.shutil, "which", lambda _: "claude.exe")
    monkeypatch.setattr(cli, "create_app", lambda *args, **kwargs: object())

    def stop_on_signal(server, sockets) -> None:
        with server.capture_signals():
            handler = signal.getsignal(shutdown_signal)
            handler(shutdown_signal, None)
        assert server.should_exit

    monkeypatch.setattr(cli._RelayForgeServer, "run", stop_on_signal)
    assert main(["serve"]) == 0


def test_cli_requires_only_default_chat_provider_and_preserves_settings(monkeypatch, tmp_path) -> None:
    repository = tmp_path / "repo"
    distribution = repository / "web" / "dist"
    distribution.mkdir(parents=True)
    (distribution / "index.html").write_text("<html></html>", encoding="utf-8")
    settings = Settings(
        workspace_dir=tmp_path,
        projects_root=tmp_path,
        home=tmp_path / "home",
        port=0,
        claude_executable="absent-claude",
        codex_executable="codex",
        chat_model="custom",
        agent_models={"codex": ("custom",)},
    )
    monkeypatch.setattr(cli, "__file__", str(repository / "src/relayforge/cli.py"))
    monkeypatch.setattr(cli, "load_settings", lambda **_: settings)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "codex.exe" if name == "codex" else None)
    observed = []
    monkeypatch.setattr(cli, "create_app", lambda effective, **_: observed.append(effective))
    monkeypatch.setattr(cli._RelayForgeServer, "run", lambda *args, **kwargs: None)
    assert main(["serve"]) == 0
    assert observed[0].codex_executable == "codex.exe"
    assert observed[0].agent_models == {"codex": ("custom",)}
    assert observed[0].chat_model == "custom"


def test_cli_backup_uses_settings_home_and_prints_json(monkeypatch, capsys, tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(
        workspace_dir=workspace,
        port=8787,
        home=tmp_path / "home",
        projects_root=tmp_path / "projects",
        claude_executable="claude",
    )
    backup_path = tmp_path / "backups" / "relayforge-backup-test"
    backup_path.mkdir(parents=True)
    counts = {"conversations": 3}
    (backup_path / "manifest.json").write_text(json.dumps({"counts": counts}), encoding="utf-8")
    monkeypatch.setattr(cli, "load_settings", lambda **_: settings)
    monkeypatch.setattr(cli, "create_backup", lambda home, output: backup_path)

    assert main(["backup", "--output", str(tmp_path / "backups")]) == 0
    assert json.loads(capsys.readouterr().out) == {"backup": str(backup_path), "counts": counts}


def test_cli_restore_uses_explicit_home_without_loading_settings(monkeypatch, capsys, tmp_path) -> None:
    result = {"schema_revision": "0014_desktop_targets", "counts": {"messages": 2}}
    monkeypatch.setattr(cli, "load_settings", lambda **_: pytest.fail("settings should not be loaded"))
    monkeypatch.setattr(cli, "restore_backup", lambda backup, home: result)

    assert main(["restore", "--from", str(tmp_path / "backup"), "--home", str(tmp_path / "new-home")]) == 0
    assert json.loads(capsys.readouterr().out) == result


def test_cli_backup_error_returns_json_and_exit_code_two(monkeypatch, capsys, tmp_path) -> None:
    from relayforge.ops.backup import BackupError

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = Settings(
        workspace_dir=workspace,
        port=8787,
        home=tmp_path / "home",
        projects_root=tmp_path / "projects",
        claude_executable="claude",
    )
    monkeypatch.setattr(cli, "load_settings", lambda **_: settings)
    monkeypatch.setattr(cli, "create_backup", lambda *_: (_ for _ in ()).throw(BackupError("bad_backup")))

    assert main(["backup"]) == 2
    assert json.loads(capsys.readouterr().err) == {"error": "bad_backup"}
