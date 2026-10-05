from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Iterable
from pathlib import Path

_PERSONAL_PATHS = (
    re.compile(r"(?i)(?<![\w])(?:[A-Z]:\\Users\\)[^\\/\s\"'<>]+"),
    re.compile(r"(?i)(?<![\w/])/(?:home|Users|root)/[^/\s\"'<>]+"),
)
_SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
    "graphify-out",
    "node_modules",
}


def personal_path_lines(content: str) -> list[int]:
    """Return only line numbers containing absolute personal home paths."""
    return [
        number
        for number, line in enumerate(content.splitlines(), start=1)
        if any(pattern.search(line) for pattern in _PERSONAL_PATHS)
    ]


def _files(root: Path) -> Iterable[Path]:
    for current, directories, filenames in os.walk(root):
        directories[:] = [name for name in directories if name not in _SKIP_DIRS]
        for filename in filenames:
            yield Path(current, filename)


def scan(root: Path) -> list[tuple[str, int]]:
    findings: list[tuple[str, int]] = []
    for path in _files(root):
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        findings.extend((path.relative_to(root).as_posix(), line) for line in personal_path_lines(content))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect absolute personal home paths without printing values."
    )
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    root = args.root.resolve(strict=True)
    findings = scan(root)
    for path, line in findings:
        print(f"{path}:{line}: personal home path detected")
    if findings:
        print(f"Found {len(findings)} personal path occurrence(s).", file=sys.stderr)
        return 1
    print("No personal home paths found.")
    return 0
