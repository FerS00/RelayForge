import subprocess
from pathlib import Path

import pytest

from relayforge.git.operations import GitError, git
from relayforge.git.worktrees import WorktreeManager


def test_worktrees_are_separate_and_diff_is_scoped(tmp_path: Path) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main", str(repository)], check=True, capture_output=True)
    (repository / "base.txt").write_text("base\n", encoding="utf-8")
    git(repository, "add", "base.txt")
    git(repository, "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-m", "base")
    base = git(repository, "rev-parse", "HEAD")
    manager = WorktreeManager(tmp_path / "runtime")
    first, first_branch = manager.create(repository, 1, base)
    second, second_branch = manager.create(repository, 2, base)
    (first / "change.txt").write_text("change\n", encoding="utf-8")
    git(first, "add", "-N", "--", ".")
    patch, paths = manager.diff(repository, first, base)
    assert first != second and first_branch != second_branch
    assert paths == ["change.txt"]
    assert "+change" in patch
    assert git(repository, "status", "--porcelain") == ""
    manager.remove(repository, first)
    manager.remove(repository, second)


def test_diff_rejects_resolved_path_outside_worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main", str(repository)], check=True, capture_output=True)
    (repository / "base.txt").write_text("base\n", encoding="utf-8")
    git(repository, "add", "base.txt")
    git(repository, "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-m", "base")
    base = git(repository, "rev-parse", "HEAD")
    worktree, _ = WorktreeManager(tmp_path / "runtime").create(repository, 1, base)
    changed = worktree / "escape.txt"
    changed.write_text("link target\n", encoding="utf-8")
    git(worktree, "add", "-N", "--", ".")

    original_resolve = Path.resolve
    outside = tmp_path / "outside.txt"

    def resolve(path: Path, strict: bool = False) -> Path:
        if path == changed:
            return outside
        return original_resolve(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(GitError, match="escapa del worktree"):
        WorktreeManager.diff(repository, worktree, base)
