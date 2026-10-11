from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from relayforge.db.session import run_migrations

_COUNT_TABLES = (
    "conversations",
    "messages",
    "chat_turns",
    "chat_actions",
    "jobs",
    "events",
    "attachments",
    "previews",
    "desktop_targets",
)


class BackupError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _is_reparse_point(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return True
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & reparse_flag)


def _iter_regular_files(root: Path) -> Iterator[Path]:
    if not root.exists() or _is_reparse_point(root) or not root.is_dir():
        return
    with os.scandir(root) as entries:
        paths = [Path(entry.path) for entry in sorted(entries, key=lambda item: item.name)]
    for path in paths:
        if _is_reparse_point(path):
            continue
        if path.is_dir():
            yield from _iter_regular_files(path)
        elif path.is_file():
            yield path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _database_metadata(path: Path) -> tuple[str, dict[str, int]]:
    try:
        with closing(sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)) as connection:
            revision_row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            if revision_row is None:
                raise BackupError("backup_source_invalid")
            tables = {
                row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            counts = {
                table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                if table in tables
                else 0
                for table in _COUNT_TABLES
            }
            return str(revision_row[0]), counts
    except (OSError, sqlite3.Error):
        raise BackupError("backup_source_invalid") from None


def _backup_file_paths(backup_dir: Path) -> set[str]:
    found: set[str] = set()
    pending = [backup_dir]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                paths = [Path(entry.path) for entry in entries]
        except OSError:
            raise BackupError("backup_integrity_failed") from None
        for path in paths:
            relative = path.relative_to(backup_dir).as_posix()
            if _is_reparse_point(path):
                raise BackupError("backup_integrity_failed")
            if path.is_dir():
                if relative != "attachments" and not relative.startswith("attachments/"):
                    raise BackupError("backup_integrity_failed")
                pending.append(path)
            elif path.is_file():
                if relative != "manifest.json":
                    if relative != "relayforge.db" and not relative.startswith("attachments/"):
                        raise BackupError("backup_integrity_failed")
                    found.add(relative)
            else:
                raise BackupError("backup_integrity_failed")
    return found


def create_backup(home: Path, output_root: Path) -> Path:
    home = home.expanduser().resolve()
    output_root = output_root.expanduser().resolve()
    data_dir = (home / "data").resolve()
    try:
        output_root.relative_to(data_dir)
    except ValueError:
        pass
    else:
        raise BackupError("backup_output_inside_data")

    source_db = home / "relayforge.db"
    if not source_db.is_file() or _is_reparse_point(source_db):
        raise BackupError("backup_source_missing")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = output_root / f"relayforge-backup-{timestamp}"
    try:
        output_root.mkdir(parents=True, exist_ok=True)
        backup_dir.mkdir()
    except FileExistsError:
        raise BackupError("backup_already_exists") from None
    except OSError:
        raise BackupError("backup_output_unavailable") from None

    try:
        source = sqlite3.connect(source_db)
        target: sqlite3.Connection | None = None
        try:
            target = sqlite3.connect(backup_dir / "relayforge.db")
            source.backup(target)
            journal_mode = target.execute("PRAGMA journal_mode=DELETE").fetchone()
            if journal_mode is None or str(journal_mode[0]).lower() != "delete":
                raise BackupError("backup_failed")
        finally:
            try:
                if target is not None:
                    target.close()
            finally:
                source.close()

        attachments_root = home / "data" / "attachments"
        backup_attachments = backup_dir / "attachments"
        backup_attachments.mkdir()
        for file_path in _iter_regular_files(attachments_root):
            relative_path = file_path.relative_to(attachments_root)
            destination = backup_attachments / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file_path, destination, follow_symlinks=False)

        schema_revision, counts = _database_metadata(backup_dir / "relayforge.db")
        files = {
            relative: _sha256(backup_dir / relative) for relative in sorted(_backup_file_paths(backup_dir))
        }
        manifest = {
            "format": 1,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "schema_revision": schema_revision,
            "counts": counts,
            "files": files,
        }
        (backup_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        return backup_dir
    except BackupError:
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise
    except (OSError, sqlite3.Error):
        shutil.rmtree(backup_dir, ignore_errors=True)
        raise BackupError("backup_failed") from None


def _read_manifest(backup_dir: Path) -> dict[str, Any]:
    manifest_path = backup_dir / "manifest.json"
    if _is_reparse_point(manifest_path) or not manifest_path.is_file():
        raise BackupError("backup_integrity_failed")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise BackupError("backup_integrity_failed") from None
    if not isinstance(manifest, dict) or manifest.get("format") != 1:
        raise BackupError("backup_integrity_failed")
    files = manifest.get("files")
    if not isinstance(files, dict) or "relayforge.db" not in files:
        raise BackupError("backup_integrity_failed")
    for relative, expected_hash in files.items():
        if (
            not isinstance(relative, str)
            or "\\" in relative
            or ":" in relative
            or PurePosixPath(relative).is_absolute()
            or PurePosixPath(relative).as_posix() != relative
            or any(part in {"", ".", ".."} for part in PurePosixPath(relative).parts)
            or (relative != "relayforge.db" and not relative.startswith("attachments/"))
            or not isinstance(expected_hash, str)
            or len(expected_hash) != 64
        ):
            raise BackupError("backup_integrity_failed")
        candidate = backup_dir.joinpath(*PurePosixPath(relative).parts)
        if any(_is_reparse_point(parent) for parent in candidate.parents if parent != backup_dir.parent):
            raise BackupError("backup_integrity_failed")
        if _is_reparse_point(candidate) or not candidate.is_file():
            raise BackupError("backup_integrity_failed")
        if _sha256(candidate) != expected_hash:
            raise BackupError("backup_integrity_failed")
    counts = manifest.get("counts")
    if (
        not isinstance(counts, dict)
        or set(counts) != set(_COUNT_TABLES)
        or any(not isinstance(counts[key], int) or counts[key] < 0 for key in _COUNT_TABLES)
        or not isinstance(manifest.get("schema_revision"), str)
    ):
        raise BackupError("backup_integrity_failed")
    if set(files) != _backup_file_paths(backup_dir):
        raise BackupError("backup_integrity_failed")
    revision, actual_counts = _database_metadata(backup_dir / "relayforge.db")
    if revision != manifest["schema_revision"] or actual_counts != counts:
        raise BackupError("backup_integrity_failed")
    return manifest


def restore_backup(backup_dir: Path, target_home: Path) -> dict[str, Any]:
    backup_dir = backup_dir.expanduser().resolve()
    target_path = target_home.expanduser().absolute()
    if target_path.is_symlink() or (target_path.exists() and _is_reparse_point(target_path)):
        raise BackupError("restore_target_not_empty")
    target_home = target_path.resolve()
    if target_home.exists():
        if not target_home.is_dir() or _is_reparse_point(target_home):
            raise BackupError("restore_target_not_empty")
        try:
            if next(target_home.iterdir(), None) is not None:
                raise BackupError("restore_target_not_empty")
        except OSError:
            raise BackupError("restore_target_not_empty") from None

    manifest = _read_manifest(backup_dir)
    try:
        target_home.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(backup_dir / "relayforge.db", target_home / "relayforge.db")
        attachment_files = {
            relative: path
            for relative, path in (
                (name, backup_dir.joinpath(*PurePosixPath(name).parts)) for name in manifest["files"]
            )
            if relative.startswith("attachments/")
        }
        attachment_target = target_home / "data" / "attachments"
        attachment_target.mkdir(parents=True, exist_ok=True)
        for relative, source in attachment_files.items():
            destination = attachment_target.joinpath(*PurePosixPath(relative).parts[1:])
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        run_migrations(target_home / "relayforge.db")
        restored_db = sqlite3.connect(target_home / "relayforge.db")
        try:
            journal_mode = restored_db.execute("PRAGMA journal_mode=DELETE").fetchone()
            if journal_mode is None or str(journal_mode[0]).lower() != "delete":
                raise BackupError("restore_failed")
        finally:
            restored_db.close()
        schema_revision, counts = _database_metadata(target_home / "relayforge.db")
    except BackupError:
        raise
    except (OSError, sqlite3.Error, SQLAlchemyError):
        raise BackupError("restore_failed") from None
    if counts != manifest["counts"]:
        raise BackupError("restore_count_mismatch")
    return {"schema_revision": schema_revision, "counts": counts}
