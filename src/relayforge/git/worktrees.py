from __future__ import annotations

import os
import threading
from collections import defaultdict
from pathlib import Path

from relayforge.git.operations import GitError, git


class WorktreeManager:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._locks: defaultdict[str, threading.RLock] = defaultdict(threading.RLock)

    def create(self, repository: Path, number: int, base_sha: str) -> tuple[Path, str]:
        repository = repository.resolve(strict=True)
        display_id = f"JOB-{number:06d}"
        branch = f"agent/job-{number}"
        path = self.root / repository.name / display_id
        with self._locks[str(repository).casefold()]:
            self.root.mkdir(parents=True, exist_ok=True)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                raise GitError("Ya existe la ruta asignada al Job.")
            git(repository, "worktree", "add", "-b", branch, str(path), base_sha)
            try:
                git(repository, "worktree", "lock", str(path), "--reason", f"RelayForge {display_id}")
            except GitError:
                git(repository, "worktree", "remove", "--force", str(path))
                raise
        return path, branch

    def remove(self, repository: Path, worktree: Path) -> None:
        repository = repository.resolve(strict=True)
        target = worktree.resolve(strict=True)
        if not target.is_relative_to(self.root.resolve()):
            raise GitError("El worktree está fuera del directorio de runtime.")
        with self._locks[str(repository).casefold()]:
            git(repository, "worktree", "unlock", str(target), timeout=30) if self._is_locked(
                repository, target
            ) else None
            git(repository, "worktree", "remove", "--force", str(target), timeout=60)
            git(repository, "worktree", "prune", timeout=60)

    @staticmethod
    def _is_locked(repository: Path, worktree: Path) -> bool:
        entries = git(repository, "worktree", "list", "--porcelain").split("\n\n")
        target = os.path.normcase(str(worktree.resolve())).replace("/", "\\")
        for entry in entries:
            lines = entry.splitlines()
            if not lines or not lines[0].startswith("worktree "):
                continue
            listed = os.path.normcase(lines[0][len("worktree ") :]).replace("/", "\\")
            if listed == target and any(line.startswith("locked") for line in lines[1:]):
                return True
        return False

    @staticmethod
    def diff(repository: Path, worktree: Path, base_sha: str) -> tuple[str, list[str]]:
        root = worktree.resolve(strict=True)
        paths = git(root, "diff", "--name-only", "--no-ext-diff", base_sha).splitlines()
        for relative in paths:
            changed = root / relative
            try:
                changed.resolve(strict=False).relative_to(root)
            except ValueError as exc:
                raise GitError("El diff incluye una ruta que escapa del worktree.") from exc
        patch = git(root, "diff", "--no-ext-diff", "--no-color", base_sha, timeout=60)
        return patch, paths
