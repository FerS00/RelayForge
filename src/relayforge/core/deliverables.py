from __future__ import annotations

import os
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from relayforge.db.models import Conversation, Job

MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_ZIP_FILES = 10_000
MAX_ZIP_BYTES = 512 * 1024 * 1024
MAX_LIST_ENTRIES = 2_000
_EXCLUDED_DIRECTORIES = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".codex",
    ".claude",
    ".gemini",
    ".ssh",
}
_EXCLUDED_FILES = {
    "auth.json",
    "credentials.json",
    ".npmrc",
    ".pypirc",
    ".netrc",
}
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(10)),
    *(f"LPT{i}" for i in range(10)),
}
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class DeliverableError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Root:
    ref: str
    name: str
    path: Path


def roots(session: Session, conversation_id: str) -> list[Root]:
    conversation = session.get(Conversation, conversation_id)
    if conversation is None:
        return []
    result: list[Root] = []
    workspace = _existing_directory(Path(conversation.workspace_dir))
    if workspace is not None:
        result.append(Root("workspace", "Workspace", workspace))
    jobs = session.scalars(
        select(Job)
        .where(Job.conversation_id == conversation_id, Job.worktree_path.is_not(None))
        .order_by(Job.number)
    )
    for job in jobs:
        path = _existing_directory(Path(job.worktree_path or ""))
        if path is not None:
            result.append(Root(f"job:{job.id}", f"Job {job.number:06d}", path))
    return result


def find_root(session: Session, conversation_id: str, root_ref: str) -> Root:
    for item in roots(session, conversation_id):
        if item.ref == root_ref:
            return item
    raise DeliverableError("file_not_found")


def resolve(root: Root, rel: str) -> Path:
    parts = _relative_parts(rel)
    base = _existing_directory(root.path)
    if base is None:
        raise DeliverableError("file_not_found")
    target = base
    for part in parts:
        if _excluded(part):
            raise DeliverableError("file_not_found")
        target = target / part
        try:
            info = target.lstat()
        except FileNotFoundError:
            raise DeliverableError("file_not_found") from None
        except OSError:
            raise DeliverableError("path_rejected") from None
        if _is_reparse(info):
            raise DeliverableError("path_rejected")
    try:
        resolved = target.resolve(strict=True)
    except (OSError, RuntimeError):
        raise DeliverableError("file_not_found") from None
    if not resolved.is_relative_to(base):
        raise DeliverableError("path_rejected")
    try:
        info = resolved.lstat()
    except OSError:
        raise DeliverableError("file_not_found") from None
    if _is_reparse(info):
        raise DeliverableError("path_rejected")
    return resolved


def list_directory(root: Root, rel: str) -> dict[str, Any]:
    directory = resolve(root, rel)
    if not directory.is_dir():
        raise DeliverableError("file_not_found")
    rows: list[dict[str, Any]] = []
    try:
        with os.scandir(directory) as scan:
            for entry in scan:
                if _excluded(entry.name):
                    continue
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if _is_reparse(info) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                    continue
                rows.append(
                    {
                        "name": entry.name,
                        "directory": stat.S_ISDIR(info.st_mode),
                        "size_bytes": 0 if stat.S_ISDIR(info.st_mode) else info.st_size,
                        "modified_at": datetime.fromtimestamp(info.st_mtime, UTC).isoformat(),
                    }
                )
    except OSError:
        raise DeliverableError("file_not_found") from None
    rows.sort(key=lambda row: (str(row["name"]).casefold(), str(row["name"])))
    return {"entries": rows[:MAX_LIST_ENTRIES], "truncated": len(rows) > MAX_LIST_ENTRIES}


def file_size(root: Root, rel: str) -> tuple[Path, int]:
    path = resolve(root, rel)
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        raise DeliverableError("file_not_found") from None
    if not stat.S_ISREG(info.st_mode):
        raise DeliverableError("file_not_found")
    if info.st_size > MAX_FILE_BYTES:
        raise DeliverableError("file_too_large")
    return path, info.st_size


def read_file(root: Root, rel: str) -> tuple[Path, bytes]:
    path, size = file_size(root, rel)
    try:
        with path.open("rb") as source:
            opened = os.fstat(source.fileno())
            current = path.lstat()
            if (
                _is_reparse(opened)
                or _is_reparse(current)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
            ):
                raise DeliverableError("path_rejected")
            content = source.read(MAX_FILE_BYTES + 1)
    except DeliverableError:
        raise
    except OSError:
        raise DeliverableError("file_not_found") from None
    if len(content) > MAX_FILE_BYTES or len(content) > size:
        raise DeliverableError("file_too_large")
    return path, content


def zip_stream(root: Root, rel: str, temp_dir: Path) -> Path:
    directory = resolve(root, rel)
    if not directory.is_dir():
        raise DeliverableError("file_not_found")
    entries: list[tuple[str, Path, os.stat_result]] = []
    total_bytes = 0
    file_count = 0
    stack: list[tuple[Path, str]] = [(directory, "")]
    try:
        while stack:
            current, prefix = stack.pop()
            with os.scandir(current) as scan:
                children = sorted(scan, key=lambda item: item.name.casefold(), reverse=True)
            for entry in children:
                if _excluded(entry.name):
                    continue
                relative = f"{prefix}/{entry.name}" if prefix else entry.name
                try:
                    # DirEntry.stat() leaves st_ino/st_dev at zero on Windows.
                    info = os.lstat(entry.path)
                except OSError:
                    continue
                if _is_reparse(info):
                    continue
                if stat.S_ISDIR(info.st_mode):
                    stack.append((Path(entry.path), relative))
                    entries.append((relative.rstrip("/") + "/", Path(entry.path), info))
                elif stat.S_ISREG(info.st_mode):
                    file_count += 1
                    total_bytes += info.st_size
                    entries.append((relative, Path(entry.path), info))
                    if total_bytes > MAX_ZIP_BYTES or file_count > MAX_ZIP_FILES:
                        raise DeliverableError("zip_too_large")
    except DeliverableError:
        raise
    except OSError:
        raise DeliverableError("file_not_found") from None

    temp_dir.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix="relayforge-", suffix=".zip", dir=temp_dir)
    os.close(descriptor)
    archive = Path(temp_name)
    try:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
            for name, path, prior_info in entries:
                if name.endswith("/"):
                    zip_info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    zip_info.external_attr = 0o40755 << 16
                    output.writestr(zip_info, b"")
                    continue
                try:
                    current_info = path.lstat()
                    if _is_reparse(current_info) or not stat.S_ISREG(current_info.st_mode):
                        raise DeliverableError("path_rejected")
                    if (current_info.st_dev, current_info.st_ino) != (prior_info.st_dev, prior_info.st_ino):
                        raise DeliverableError("path_rejected")
                    zip_info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                    zip_info.compress_type = zipfile.ZIP_DEFLATED
                    with path.open("rb") as source, output.open(zip_info, "w", force_zip64=True) as target:
                        opened_info = os.fstat(source.fileno())
                        if _is_reparse(opened_info) or (opened_info.st_dev, opened_info.st_ino) != (
                            current_info.st_dev,
                            current_info.st_ino,
                        ):
                            raise DeliverableError("path_rejected")
                        copied = 0
                        while chunk := source.read(1024 * 1024):
                            copied += len(chunk)
                            if copied > prior_info.st_size or copied > MAX_ZIP_BYTES:
                                raise DeliverableError("zip_too_large")
                            target.write(chunk)
                except DeliverableError:
                    raise
                except OSError:
                    raise DeliverableError("file_not_found") from None
        return archive
    except BaseException:
        archive.unlink(missing_ok=True)
        raise


def _relative_parts(rel: str) -> tuple[str, ...]:
    if not isinstance(rel, str) or "\x00" in rel or "\\" in rel or rel.startswith("/"):
        raise DeliverableError("path_rejected")
    if not rel:
        return ()
    parts = rel.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise DeliverableError("path_rejected")
    for part in parts:
        stem = part.split(".", 1)[0].rstrip(" .").upper()
        if (
            ":" in part
            or part.endswith((".", " "))
            or any(character in part for character in '<>|?*"')
            or stem in _WINDOWS_RESERVED
        ):
            raise DeliverableError("path_rejected")
    return tuple(parts)


def _excluded(name: str) -> bool:
    folded = name.casefold()
    return (
        folded in _EXCLUDED_DIRECTORIES
        or folded in _EXCLUDED_FILES
        or folded.startswith(".env")
        or folded.endswith((".pem", ".key", ".pfx", ".p12"))
        or folded.startswith(("id_rsa", "id_ed25519"))
    )


def _is_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _existing_directory(path: Path) -> Path | None:
    try:
        resolved = path.resolve(strict=True)
        if resolved.is_dir():
            return resolved
    except (OSError, RuntimeError):
        pass
    return None
