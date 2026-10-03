"""Localización segura de los ejecutables de agentes."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class AgentBinary:
    name: str
    path: Path | None
    source: str


def locate(name: str, env: Mapping[str, str] = os.environ) -> AgentBinary:
    """Busca un binario por variable dedicada, PATH y ubicación conocida de Codex."""
    key = f"RELAYFORGE_{name.upper()}_BIN"
    candidate = Path(env[key]).expanduser() if env.get(key) else None
    if candidate is not None and candidate.is_file():
        return AgentBinary(name, candidate.resolve(), "env")

    on_path = shutil.which(name, path=env.get("PATH"))
    if on_path:
        return AgentBinary(name, Path(on_path).resolve(), "path")

    if name == "codex" and os.name == "nt":
        local_app_data = env.get("LOCALAPPDATA")
        if local_app_data:
            root = Path(local_app_data) / "OpenAI" / "Codex" / "bin"
            candidates = list(root.glob("*/codex.exe"))
            candidates = [item for item in candidates if item.is_file()]
            if candidates:
                latest = max(candidates, key=lambda item: item.stat().st_mtime)
                return AgentBinary(name, latest.resolve(), "known_location")
    return AgentBinary(name, None, "missing")


def version(binary: AgentBinary, timeout: float = 20) -> str | None:
    if binary.path is None:
        return None
    try:
        result = subprocess.run(
            [str(binary.path), "--version"], capture_output=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    return text.splitlines()[0] if text.splitlines() else None
