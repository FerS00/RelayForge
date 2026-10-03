"""Escritura de evidencia con redacción obligatoria."""

from __future__ import annotations

import json
import platform
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from common.binaries import locate, version
from common.redact import redact


class Evidence:
    def __init__(self, poc_id: str, root: Path | None = None):
        if root is None:
            root = Path(__file__).resolve().parents[1] / "results" / poc_id / datetime.now().strftime("%Y%m%d-%H%M%S")
        self.dir = Path(root).resolve()
        self.dir.mkdir(parents=True, exist_ok=True)

    def write_text(self, name: str, text: str) -> Path:
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(redact(text), encoding="utf-8", newline="\n")
        return path

    def write_json(self, name: str, data: Any) -> Path:
        return self.write_text(name, json.dumps(data, ensure_ascii=False, indent=2))

    def record_versions(self) -> dict[str, str | None]:
        git_version: str | None
        try:
            result = subprocess.run(["git", "--version"], capture_output=True, timeout=10, check=False)
            git_version = (result.stdout + result.stderr).decode("utf-8", errors="replace").splitlines()[0]
        except (OSError, subprocess.TimeoutExpired):
            git_version = None
        result = {
            "SO": platform.platform(),
            "python": platform.python_version(),
            "git": git_version,
            **{name: version(locate(name)) for name in ("claude", "codex", "agy")},
        }
        self.write_json("versions.json", result)
        return result

    def verdict(self, status: Literal["PASS", "FAIL", "MANUAL"], criteria: list[dict]) -> Path:
        return self.write_json("verdict.json", {"status": status, "criteria": criteria})
