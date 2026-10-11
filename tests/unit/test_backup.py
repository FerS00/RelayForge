from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from relayforge.db.session import run_migrations
from relayforge.ops.backup import BackupError, create_backup, restore_backup


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    run_migrations(home / "relayforge.db")
    return home


def test_create_backup_copies_only_database_and_regular_attachments(tmp_path: Path) -> None:
    home = _home(tmp_path)
    attachment_dir = home / "data" / "attachments"
    attachment_dir.mkdir(parents=True)
    (attachment_dir / "nested").mkdir()
    (attachment_dir / "nested" / "file.bin").write_bytes(b"attachment")
    outside_attachment = tmp_path / "outside.bin"
    outside_attachment.write_bytes(b"must not be copied")
    symlink_path = attachment_dir / "outside-link.bin"
    try:
        symlink_path.symlink_to(outside_attachment)
    except OSError:
        symlink_available = False
    else:
        symlink_available = True
    (home / "config").mkdir()
    (home / "config" / "settings.yaml").write_text("secret: excluded", encoding="utf-8")
    (home / "data" / "chat").mkdir()
    (home / "data" / "chat" / "process.log").write_text("excluded", encoding="utf-8")
    (home / "desktop-files").mkdir()
    (home / "desktop-files" / "note.txt").write_text("excluded", encoding="utf-8")

    backup_dir = create_backup(home, tmp_path / "backups")
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))

    assert backup_dir.name.startswith("relayforge-backup-")
    assert manifest["format"] == 1
    assert manifest["schema_revision"] == "0014_desktop_targets"
    assert manifest["counts"]["attachments"] == 0
    assert set(manifest["files"]) == {"relayforge.db", "attachments/nested/file.bin"}
    assert symlink_available is False or not (backup_dir / "attachments" / "outside-link.bin").exists()
    assert not (backup_dir / "config").exists()
    assert not (backup_dir / "desktop-files").exists()


def test_create_backup_rejects_output_inside_data(tmp_path: Path) -> None:
    home = _home(tmp_path)
    with pytest.raises(BackupError, match="backup_output_inside_data"):
        create_backup(home, home / "data" / "backups")


def test_restore_rejects_invalid_manifest_without_creating_target(tmp_path: Path) -> None:
    home = _home(tmp_path)
    backup_dir = create_backup(home, tmp_path / "backups")
    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["format"] = 2
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    target_home = tmp_path / "restore"

    with pytest.raises(BackupError, match="backup_integrity_failed"):
        restore_backup(backup_dir, target_home)
    assert not target_home.exists()


def test_restore_refuses_any_nonempty_target_without_changes(tmp_path: Path) -> None:
    home = _home(tmp_path)
    backup_dir = create_backup(home, tmp_path / "backups")
    target_home = tmp_path / "restore"
    target_home.mkdir()
    marker = target_home / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(BackupError, match="restore_target_not_empty"):
        restore_backup(backup_dir, target_home)
    assert list(target_home.iterdir()) == [marker]


def test_backup_uses_sqlite_backup_api_for_wal_database(tmp_path: Path) -> None:
    home = _home(tmp_path)
    connection = sqlite3.connect(home / "relayforge.db", isolation_level=None)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "INSERT INTO conversations "
            "(id, title, workspace_dir, orchestrator, session_id, "
            "session_established, created_at, updated_at) "
            "VALUES ('wal-c', 'WAL', '/workspace', 'codex', 'session', 0, 't', 't')"
        )
        backup_dir = create_backup(home, tmp_path / "backups")
        backup_db = sqlite3.connect(backup_dir / "relayforge.db")
        try:
            assert backup_db.execute("SELECT COUNT(*) FROM conversations").fetchone() == (1,)
            assert backup_db.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        finally:
            backup_db.close()
        assert {path.name for path in backup_dir.iterdir()} == {
            "relayforge.db",
            "attachments",
            "manifest.json",
        }
        assert not (backup_dir / "relayforge.db-wal").exists()
        assert not (backup_dir / "relayforge.db-shm").exists()
    finally:
        connection.close()
