from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from relayforge.doctor.checks import _run_cli

_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}")
_MAX_CACHE_BYTES = 2 * 1024 * 1024


def _codex_rows() -> list[object]:
    cache = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))) / "models_cache.json"
    try:
        with cache.open("rb") as stream:
            raw = stream.read(_MAX_CACHE_BYTES + 1)
        if len(raw) > _MAX_CACHE_BYTES:
            return []
        data = json.loads(raw)
    except (OSError, ValueError):
        return []
    rows = data.get("models") if isinstance(data, dict) else None
    return rows if isinstance(rows, list) else []


def discover_efforts(agent: str) -> dict[str, tuple[str, ...]]:
    """Reasoning levels advertised per Codex model; other agents expose no catalog."""
    if agent != "codex":
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for row in _codex_rows():
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("slug"), str)
            or not _MODEL.fullmatch(row["slug"])
        ):
            continue
        levels = row.get("supported_reasoning_levels")
        if not isinstance(levels, list):
            continue
        result[row["slug"]] = tuple(
            str(level["effort"])
            for level in levels
            if isinstance(level, dict) and isinstance(level.get("effort"), str)
        )
    return result


def discover_models(agent: str, executable: str) -> list[str]:
    """Read advertised identifiers only; never load or return authentication files."""
    if agent == "codex":
        rows = _codex_rows()
        if not rows:
            return []
        return list(
            dict.fromkeys(
                row["slug"]
                for row in rows
                if isinstance(row, dict)
                and row.get("visibility") == "list"
                and isinstance(row.get("slug"), str)
                and _MODEL.fullmatch(row["slug"])
            )
        )
    if agent not in {"claude", "antigravity"}:
        return []
    binary = shutil.which(executable)
    if binary is None:
        return []
    try:
        result = _run_cli([binary, "models" if agent == "antigravity" else "--help"])
    except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    if agent == "antigravity":
        candidates = [line.split("\t", 1)[0].strip() for line in result.stdout.splitlines() if "\t" in line]
    else:
        # Extract aliases from the --model help block, not unrelated examples.
        block = re.search(r"--model\s+<model>(.*?)(?=\n\s+--?\w|\Z)", result.stdout, re.S)
        candidates = re.findall(r"'([^']+)'", block.group(1)) if block else []
    return list(dict.fromkeys(model for model in candidates if _MODEL.fullmatch(model)))
