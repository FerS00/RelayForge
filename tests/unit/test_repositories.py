import subprocess
from pathlib import Path

import pytest

from relayforge.core.repositories import RepositoryError, RepositoryService
from relayforge.db.session import create_db_engine, make_session_factory, run_migrations


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def test_register_existing_repo_reports_dirty_without_changing_checkout(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main", str(root)], check=True, capture_output=True)
    _git(
        root,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@localhost",
        "commit",
        "--allow-empty",
        "-m",
        "init",
    )
    (root / "uncommitted.txt").write_text("keep me", encoding="utf-8")
    before = _git(root, "status", "--porcelain")
    database = tmp_path / "db.sqlite"
    run_migrations(database)
    engine = create_db_engine(database)
    try:
        service = RepositoryService(make_session_factory(engine), tmp_path / "projects")
        result = service.register("existing", str(root))
        assert result["dirty"] is True
        assert _git(root, "status", "--porcelain") == before
    finally:
        engine.dispose()


def test_create_repo_is_contained_and_has_initial_commit(tmp_path: Path) -> None:
    database = tmp_path / "db.sqlite"
    run_migrations(database)
    engine = create_db_engine(database)
    try:
        projects = tmp_path / "projects"
        service = RepositoryService(make_session_factory(engine), projects)
        result = service.create("new-project")
        assert Path(result["path"]).parent == projects
        assert result["default_branch"] == "main"
        assert _git(Path(result["path"]), "rev-list", "--count", "HEAD") == "1"
        with pytest.raises(RepositoryError):
            service.create("../escape")
        with pytest.raises(RepositoryError):
            service.create("new-project")
    finally:
        engine.dispose()
