from __future__ import annotations

import argparse
import logging
import shutil
import signal
import socket
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import uvicorn

from relayforge.api.app import create_app
from relayforge.settings import SettingsError, load_settings


class _RelayForgeServer(uvicorn.Server):
    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        await super().startup(sockets=sockets)
        if self.started:
            print(f"RelayForge: http://127.0.0.1:{self.config.port}", flush=True)

    @contextmanager
    def capture_signals(self) -> Iterator[None]:
        if threading.current_thread() is not threading.main_thread():
            yield
            return
        signals = [signal.SIGINT, signal.SIGTERM]
        sigbreak = getattr(signal, "SIGBREAK", None)
        if sigbreak is not None:
            signals.append(sigbreak)
        original_handlers = {sig: signal.signal(sig, self.handle_exit) for sig in signals}
        try:
            yield
        finally:
            for sig, handler in original_handlers.items():
                signal.signal(sig, handler)


def _bind_listener(port: int) -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind(("127.0.0.1", port))
        listener.listen()
    except OSError:
        listener.close()
        raise SettingsError(
            f"El puerto {port} de 127.0.0.1 ya está en uso; usa --port o RELAYFORGE_PORT."
        ) from None
    return listener


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="relayforge")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve")
    serve.add_argument("--port", type=int)
    args = parser.parse_args(argv)
    listener: socket.socket | None = None
    try:
        settings = load_settings(**({"port": args.port} if args.port is not None else {}))
        executable = shutil.which(settings.claude_executable)
        if executable is None:
            raise SettingsError("No se encontró el ejecutable configurado de Claude Code.")
        settings = type(settings)(
            workspace_dir=settings.workspace_dir,
            port=settings.port,
            home=settings.home,
            claude_executable=executable,
            claude_model=settings.claude_model,
        )
        listener = _bind_listener(settings.port)
        distribution = Path(__file__).resolve().parents[2] / "web" / "dist"
        if not (distribution / "index.html").is_file():
            raise SettingsError("Falta web/dist/index.html; ejecuta npm --prefix web run build.")
        for directory in (settings.home / "config", settings.home / "data", settings.home / "logs"):
            directory.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            filename=settings.home / "logs" / "relayforge.log",
            encoding="utf-8",
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
        app = create_app(settings, web_dist=distribution)
        config = uvicorn.Config(
            app, host="127.0.0.1", port=settings.port, workers=1, reload=False, log_config=None
        )
        _RelayForgeServer(config).run(sockets=[listener])
        return 0
    except SettingsError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        logging.getLogger("relayforge").exception("server failed")
        print("RelayForge no pudo iniciar por un error interno.", file=sys.stderr)
        return 1
    finally:
        if listener is not None:
            listener.close()
