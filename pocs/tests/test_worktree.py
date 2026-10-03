from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from setup_sandbox_repo import setup


def test_worktree_runner_passes(tmp_path: Path) -> None:
    repo = setup(tmp_path / "sandbox", with_submodule=True)
    env = dict(os.environ)
    env["RELAYFORGE_POC_RUNTIME"] = str(tmp_path / "runtime")
    result = subprocess.run([sys.executable, str(Path(__file__).parents[1] / "poc05_worktree" / "run.py"),
                             "--repo", str(repo), "--runtime", str(tmp_path / "runtime")],
                            cwd=Path(__file__).parents[1], env=env, capture_output=True, timeout=90, check=False)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    results = Path(__file__).parents[1] / "results" / "poc05_worktree"
    verdict_files = sorted(results.glob("*/verdict.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    assert verdict_files
    import json

    assert json.loads(verdict_files[0].read_text(encoding="utf-8"))["status"] == "PASS"
