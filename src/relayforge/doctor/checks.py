from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from relayforge.adapters.base import LaunchPlan
from relayforge.process.supervisor import Supervisor
from relayforge.settings import Settings


def _run_cli(argv: list[str], *, timeout: float = 5) -> subprocess.CompletedProcess[str]:
    """Bound launcher and child lifetimes without inherited-pipe waits."""
    supervisor = Supervisor()
    with tempfile.TemporaryDirectory(prefix="relayforge-probe-") as directory:
        root = Path(directory)
        handle = supervisor.start(
            LaunchPlan(tuple(argv), root, ""),
            output_path=root / "stdout",
            stderr_path=root / "stderr",
        )
        try:
            code = handle.process.wait(timeout=timeout)
        finally:
            supervisor.kill(handle)
        with handle.output_path.open("rb") as output, handle.stderr_path.open("rb") as error:
            return subprocess.CompletedProcess(
                argv,
                code,
                output.read(65536).decode("utf-8", errors="replace"),
                error.read(65536).decode("utf-8", errors="replace"),
            )


def _probe(argv: list[str]) -> dict[str, str]:
    executable = shutil.which(argv[0])
    if executable is None:
        return {"status": "NOT_INSTALLED", "version": ""}
    try:
        result = _run_cli([executable, *argv[1:]])
    except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired):
        return {"status": "UNKNOWN", "version": ""}
    output = (result.stdout or result.stderr).strip().splitlines()
    match = re.search(r"\b\d+(?:\.\d+){1,3}(?:[-+][A-Za-z0-9.-]+)?\b", output[0]) if output else None
    return {
        "status": "AVAILABLE" if result.returncode == 0 else "UNKNOWN",
        "version": match.group(0) if match else "",
    }


def _agent(executable_name: str, auth_args: list[str] | None = None) -> dict[str, str]:
    executable = shutil.which(executable_name)
    if executable is None:
        return {"status": "NOT_INSTALLED", "version": "", "auth": "UNKNOWN"}
    version = _probe([executable, "--version"])
    auth = "UNKNOWN"
    if auth_args is not None:
        try:
            result = _run_cli([executable, *auth_args])
        except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired):
            result = None
        if result is not None:
            output = result.stdout + result.stderr
            executable_label = Path(executable).name.lower()
            if executable_label.startswith("claude"):
                try:
                    payload = json.loads(output)
                except json.JSONDecodeError:
                    payload = {}
                auth = "AVAILABLE" if payload.get("loggedIn") is True else "AUTH_REQUIRED"
            elif executable_label.startswith("codex"):
                auth = "AVAILABLE" if result.returncode == 0 else "AUTH_REQUIRED"
    return {"status": version["status"], "version": version["version"], "auth": auth}


def fingerprint() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[3]
    digest = hashlib.sha256()
    for folder in (root / "config" / "policies", root / "config" / "workflows"):
        if folder.is_dir():
            for path in sorted(folder.rglob("*.yaml")):
                digest.update(path.relative_to(root).as_posix().encode())
                digest.update(path.read_bytes())
    return {
        "schema": 1,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": sys.platform,
        "config_sha256": digest.hexdigest(),
        "agents": {name: _agent(name)["version"] for name in ("claude", "codex", "agy")},
    }


def doctor_report(settings: Settings, engine: Engine) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "bind": {"status": "PASS" if settings.bind == "127.0.0.1" else "FAIL"},
        "git": _probe(["git", "--version"]),
        "tailscale": _probe(["tailscale", "version"]),
        "docker": _probe(["docker", "--version"]),
        "claude": _agent(settings.claude_executable, ["auth", "status"]),
        "codex": _agent(settings.codex_executable, ["login", "status"]),
        "agy": _agent("agy"),
        "disk_free_bytes": shutil.disk_usage(settings.home).free,
    }
    try:
        with engine.connect() as connection:
            checks["database"] = {
                "status": "PASS"
                if connection.execute(text("PRAGMA integrity_check")).scalar() == "ok"
                else "FAIL"
            }
    except Exception:
        checks["database"] = {"status": "FAIL"}
    checks["fingerprint"] = fingerprint()
    return checks


def compare_fingerprint(path: Path) -> dict[str, Any]:
    try:
        previous = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "ERROR", "message": "No se pudo leer un fingerprint JSON válido."}
    current = fingerprint()
    differences = {
        key: {"local": previous.get(key), "current": current.get(key)}
        for key in sorted(set(previous) | set(current))
        if previous.get(key) != current.get(key)
    }
    return {"status": "MATCH" if not differences else "DIFFERENT", "differences": differences}
