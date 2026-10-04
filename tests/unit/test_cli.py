import signal
import socket

import pytest

from relayforge import cli
from relayforge.cli import main
from relayforge.settings import Settings


def test_cli_reports_missing_workspace(monkeypatch, capsys) -> None:
    monkeypatch.setenv("LOCALAPPDATA", ".")
    monkeypatch.delenv("RELAYFORGE_WORKSPACE_DIR", raising=False)
    assert main(["serve"]) == 2
    assert "obligatorio" in capsys.readouterr().err


def test_cli_rejects_occupied_port_without_printing_url(monkeypatch, capsys, tmp_path) -> None:
    occupied = socket.socket()
    occupied.bind(("127.0.0.1", 0))
    occupied.listen()
    port = occupied.getsockname()[1]
    settings = Settings(
        workspace_dir=tmp_path,
        port=port,
        home=tmp_path / "home",
        claude_executable="claude",
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
        claude_executable="claude",
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
