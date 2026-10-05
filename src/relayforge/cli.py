from __future__ import annotations

import argparse
import json
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
from relayforge.core.auth import AuthService
from relayforge.core.repositories import RepositoryError, RepositoryService
from relayforge.db.session import create_db_engine, make_session_factory, run_migrations
from relayforge.doctor.checks import compare_fingerprint, doctor_report, fingerprint
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


def _bind_listener(port: int, bind: str = "127.0.0.1") -> socket.socket:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        listener.bind((bind, port))
        listener.listen()
    except OSError:
        listener.close()
        raise SettingsError(
            f"El puerto {port} de {bind} ya está en uso; usa --port o RELAYFORGE_PORT."
        ) from None
    return listener


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="relayforge")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve")
    serve.add_argument("--port", type=int)
    repo = subparsers.add_parser("repo")
    repo_commands = repo.add_subparsers(dest="repo_command", required=True)
    add_repo = repo_commands.add_parser("add")
    add_repo.add_argument("name")
    add_repo.add_argument("path", type=Path)
    token = subparsers.add_parser("token")
    token_commands = token.add_subparsers(dest="token_command", required=True)
    token_commands.add_parser("pair")
    doctor = subparsers.add_parser("doctor")
    doctor_modes = doctor.add_mutually_exclusive_group()
    doctor_modes.add_argument("--fingerprint", action="store_true")
    doctor_modes.add_argument("--compare", type=Path)
    gate = subparsers.add_parser("gate")
    gate.add_argument("--policy", type=Path, required=True)
    dispatcher = subparsers.add_parser("check-dispatch")
    dispatcher.add_argument("--policy", type=Path, required=True)
    dispatcher.add_argument("--command", dest="command_name", required=True)
    args = parser.parse_args(argv)
    listener: socket.socket | None = None
    try:
        if args.command == "gate":
            from relayforge.adapters.antigravity.gate import main as run_gate

            return run_gate(["--policy", str(args.policy)])
        if args.command == "check-dispatch":
            from relayforge.adapters.antigravity.gate import dispatch

            return dispatch(args.policy, args.command_name)
        port_override = getattr(args, "port", None)
        settings = load_settings(**({"port": port_override} if port_override is not None else {}))
        if args.command == "doctor":
            if args.fingerprint:
                print(json.dumps(fingerprint(), ensure_ascii=False, sort_keys=True, indent=2))
                return 0
            if args.compare:
                result = compare_fingerprint(args.compare)
            else:
                settings.home.mkdir(parents=True, exist_ok=True)
                db_path = settings.home / "relayforge.db"
                run_migrations(db_path)
                engine = create_db_engine(db_path)
                try:
                    result = doctor_report(settings, engine)
                finally:
                    engine.dispose()
            print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
            return 0
        if args.command == "token":
            if not settings.allowed_tailscale_logins or not settings.allowed_hosts:
                raise SettingsError(
                    "Configura RELAYFORGE_ALLOWED_TAILSCALE_LOGINS y "
                    "RELAYFORGE_ALLOWED_HOSTS antes del pairing."
                )
            settings.home.mkdir(parents=True, exist_ok=True)
            db_path = settings.home / "relayforge.db"
            run_migrations(db_path)
            engine = create_db_engine(db_path)
            try:
                code = AuthService(make_session_factory(engine)).issue_pairing_code()
            finally:
                engine.dispose()
            print(code)
            return 0
        if args.command == "repo":
            settings.home.mkdir(parents=True, exist_ok=True)
            database = settings.home / "relayforge.db"
            run_migrations(database)
            engine = create_db_engine(database)
            try:
                service = RepositoryService(make_session_factory(engine), settings.projects_root)
                result = service.register(args.name, str(args.path))
                print(json.dumps({"repository": result}, ensure_ascii=False))
            finally:
                engine.dispose()
            return 0
        executable = shutil.which(settings.claude_executable)
        if executable is None:
            raise SettingsError("No se encontró el ejecutable configurado de Claude Code.")
        settings = type(settings)(
            workspace_dir=settings.workspace_dir,
            port=settings.port,
            home=settings.home,
            projects_root=settings.projects_root,
            claude_executable=executable,
            claude_model=settings.claude_model,
            codex_executable=settings.codex_executable,
            bind=settings.bind,
            container_mode=settings.container_mode,
            trusted_proxy_ip=settings.trusted_proxy_ip,
            allowed_tailscale_logins=settings.allowed_tailscale_logins,
            allowed_hosts=settings.allowed_hosts,
        )
        listener = _bind_listener(settings.port, settings.bind)
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
            app,
            host=settings.bind,
            port=settings.port,
            workers=1,
            reload=False,
            log_config=None,
            # Auth validates the actual loopback proxy peer, not X-Forwarded-For.
            proxy_headers=False,
        )
        _RelayForgeServer(config).run(sockets=[listener])
        return 0
    except (SettingsError, RepositoryError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception:
        logging.getLogger("relayforge").exception("server failed")
        print("RelayForge no pudo iniciar por un error interno.", file=sys.stderr)
        return 1
    finally:
        if listener is not None:
            listener.close()
