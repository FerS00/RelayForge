from __future__ import annotations

import builtins
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from relayforge.adapters.checks import ChecksAdapter, ChecksValidationError
from relayforge.core.ids import new_ulid
from relayforge.db.models import Repository, utc_now
from relayforge.git.operations import GitError, repository_state

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class RepositoryError(ValueError):
    pass


class RepositoryService:
    def __init__(self, sessions: sessionmaker[Session], projects_root: Path) -> None:
        self.sessions = sessions
        self.projects_root = projects_root.resolve()

    def list(self) -> list[dict[str, Any]]:
        with self.sessions() as session:
            repos = session.scalars(select(Repository).order_by(Repository.name)).all()
            return [self._serialize(repo) for repo in repos]

    def register(
        self,
        name: str,
        path: str,
        default_branch: str | None = None,
        check_commands: builtins.list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        self._validate_name(name)
        try:
            state = repository_state(Path(path).expanduser().resolve(strict=True))
        except (OSError, GitError) as exc:
            raise RepositoryError("La ruta no apunta a un repositorio Git válido.") from exc
        root = Path(str(state["path"]))
        branch = default_branch or str(state["default_branch"])
        if not branch or branch.startswith("-"):
            raise RepositoryError("La rama por defecto no es válida.")
        return self._save(name, root, branch, dirty=bool(state["dirty"]), check_commands=check_commands or [])

    def create(
        self, name: str, check_commands: builtins.list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        self._validate_name(name)
        root = self.projects_root.resolve()
        candidate = root / name
        root.mkdir(parents=True, exist_ok=True)
        if candidate.exists():
            raise RepositoryError("Ya existe un elemento con ese nombre en projects_root.")
        if not candidate.resolve(strict=False).is_relative_to(root):
            raise RepositoryError("La ruta solicitada sale de projects_root.")
        with self.sessions() as session:
            if session.scalar(select(Repository).where(Repository.name == name)) is not None:
                raise RepositoryError("El nombre ya está registrado para otro repositorio.")
        candidate.mkdir()
        try:
            subprocess.run(
                ["git", "init", "--quiet", "--initial-branch=main", str(candidate)],
                check=True,
                capture_output=True,
                timeout=30,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(candidate),
                    "-c",
                    "user.name=RelayForge",
                    "-c",
                    "user.email=relayforge@localhost",
                    "-c",
                    "commit.gpgsign=false",
                    "commit",
                    "--allow-empty",
                    "-m",
                    "Initial commit",
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
            return self._save(
                name, candidate.resolve(strict=True), "main", dirty=False, check_commands=check_commands or []
            )
        except (OSError, subprocess.SubprocessError, RepositoryError) as exc:
            if candidate.is_dir():
                shutil.rmtree(candidate)
            if isinstance(exc, RepositoryError):
                raise
            raise RepositoryError("No se pudo inicializar el repositorio local.") from exc

    def _save(
        self,
        name: str,
        path: Path,
        branch: str,
        *,
        dirty: bool,
        check_commands: builtins.list[dict[str, Any]],
    ) -> dict[str, Any]:
        try:
            commands = [command.json() for command in ChecksAdapter.parse_many(check_commands)]
        except ChecksValidationError as exc:
            raise RepositoryError(str(exc)) from exc
        with self.sessions.begin() as session:
            existing = session.scalar(
                select(Repository).where((Repository.name == name) | (Repository.path == str(path)))
            )
            if existing is not None:
                raise RepositoryError("El nombre o la ruta ya están registrados.")
            repo = Repository(
                id=new_ulid(),
                name=name,
                path=str(path),
                default_branch=branch,
                check_commands_json=json.dumps(commands, ensure_ascii=False, separators=(",", ":")),
                policy_profile="default",
                created_at=utc_now(),
                enabled=1,
            )
            session.add(repo)
            session.flush()
            result = self._serialize(repo)
        result["dirty"] = dirty
        return result

    @staticmethod
    def _validate_name(name: str) -> None:
        if _NAME.fullmatch(name) is None or name in {".", ".."}:
            raise RepositoryError(
                "El nombre debe tener 1–64 letras, números, puntos, guiones o guiones bajos."
            )

    @staticmethod
    def _serialize(repo: Repository) -> dict[str, Any]:
        try:
            state = repository_state(Path(repo.path))
            dirty = bool(state["dirty"])
            health = "READY"
        except (OSError, GitError):
            dirty = False
            health = "UNAVAILABLE"
        return {
            "id": repo.id,
            "name": repo.name,
            "path": repo.path,
            "default_branch": repo.default_branch,
            "policy_profile": repo.policy_profile,
            "created_at": repo.created_at,
            "enabled": bool(repo.enabled),
            "dirty": dirty,
            "health": health,
            "check_commands": json.loads(repo.check_commands_json or "[]"),
        }
