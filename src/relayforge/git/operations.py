from __future__ import annotations

import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def git(repo: Path, *args: str, timeout: float = 30) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GitError("Git no pudo completar la operación.") from exc
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace").strip()
    if result.returncode:
        raise GitError(output[-2000:] or "Git terminó con error.")
    return output


def repository_state(path: Path) -> dict[str, str | bool]:
    root = Path(git(path, "rev-parse", "--show-toplevel")).resolve(strict=True)
    head = git(root, "rev-parse", "HEAD")
    branch = git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    status = git(root, "status", "--porcelain", "--untracked-files=normal")
    return {"path": str(root), "head": head, "default_branch": branch, "dirty": bool(status)}
