from __future__ import annotations

import os
from pathlib import Path

from common.binaries import locate


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return path


def test_env_precedes_path_and_known_location(tmp_path: Path, monkeypatch) -> None:
    env_binary = touch(tmp_path / "env" / "codex.exe")
    path_binary = touch(tmp_path / "path" / "codex.exe")
    known_binary = touch(tmp_path / "local" / "OpenAI" / "Codex" / "bin" / "v1" / "codex.exe")
    monkeypatch.setattr(os, "name", "nt")
    monkeypatch.setattr("common.binaries.shutil.which", lambda name, path=None: str(path_binary))
    found = locate("codex", {"RELAYFORGE_CODEX_BIN": str(env_binary), "LOCALAPPDATA": str(tmp_path / "local")})
    assert found.path == env_binary.resolve()
    assert found.source == "env"
    found = locate("codex", {"PATH": str(tmp_path / "path"), "LOCALAPPDATA": str(tmp_path / "local")})
    assert found.path == path_binary.resolve()
    assert found.source == "path"

    monkeypatch.setattr("common.binaries.shutil.which", lambda name, path=None: None)
    found = locate("codex", {"LOCALAPPDATA": str(tmp_path / "local")})
    assert found.path == known_binary.resolve()
    assert found.source == "known_location"


def test_missing_binary(monkeypatch) -> None:
    monkeypatch.setattr("common.binaries.shutil.which", lambda name, path=None: None)
    monkeypatch.setattr("common.binaries.os.name", "posix")
    assert locate("agy", {}).source == "missing"
