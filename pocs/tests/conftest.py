from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from setup_sandbox_repo import setup  # noqa: E402


def make_sandbox(path: Path) -> Path:
    return setup(path)
