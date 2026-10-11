from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from relayforge.db.session import run_migrations
from relayforge.ops.backup import BackupError, create_backup, restore_backup


def _seed_home(home: Path) -> tuple[dict[str, int], dict[str, str]]:
    home.mkdir()
    database = home / "relayforge.db"
    run_migrations(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO conversations "
            "(id, title, workspace_dir, orchestrator, session_id, "
            "session_established, created_at, updated_at) "
            "VALUES ('c1', 'Conversation', '/workspace', 'codex', 's1', 0, 't', 't')"
        )
        connection.execute(
            "INSERT INTO messages "
            "(id, conversation_id, role, content, step_id, status, ts) "
            "VALUES ('m1', 'c1', 'user', 'hello', 'step', 'complete', 't')"
        )
        connection.execute(
            "INSERT INTO events "
            "(conversation_id, seq, ts, type, actor, payload_json) "
            "VALUES ('c1', 1, 't', 'message', 'user', '{}')"
        )
    attachment_dir = home / "data" / "attachments"
    attachment_dir.mkdir(parents=True)
    attachment_data = b"saved attachment bytes"
    (attachment_dir / "stored.bin").write_bytes(attachment_data)
    return (
        {
            "conversations": 1,
            "messages": 1,
            "chat_turns": 0,
            "chat_actions": 0,
            "jobs": 0,
            "events": 1,
            "attachments": 0,
            "previews": 0,
            "desktop_targets": 0,
        },
        {"stored.bin": hashlib.sha256(attachment_data).hexdigest()},
    )


def test_backup_restore_preserves_database_counts_and_attachment_hashes(tmp_path: Path) -> None:
    source_home = tmp_path / "source"
    expected_counts, expected_hashes = _seed_home(source_home)
    backup_dir = create_backup(source_home, tmp_path / "backups")
    manifest = json.loads((backup_dir / "manifest.json").read_text(encoding="utf-8"))
    target_home = tmp_path / "restored"

    restored = restore_backup(backup_dir, target_home)

    assert restored["counts"] == expected_counts == manifest["counts"]
    assert restored["schema_revision"] == manifest["schema_revision"]
    assert {path.name for path in target_home.iterdir()} == {"relayforge.db", "data"}
    assert not (target_home / "relayforge.db-wal").exists()
    assert not (target_home / "relayforge.db-shm").exists()
    restored_attachment = target_home / "data" / "attachments" / "stored.bin"
    assert hashlib.sha256(restored_attachment.read_bytes()).hexdigest() == expected_hashes["stored.bin"]
    with sqlite3.connect(target_home / "relayforge.db") as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert connection.execute("SELECT content FROM messages WHERE id = 'm1'").fetchone() == ("hello",)


def test_restore_detects_changed_database_hash_before_writing(tmp_path: Path) -> None:
    source_home = tmp_path / "source"
    _seed_home(source_home)
    backup_dir = create_backup(source_home, tmp_path / "backups")
    (backup_dir / "relayforge.db").write_bytes(b"changed")
    target_home = tmp_path / "restored"

    with pytest.raises(BackupError, match="backup_integrity_failed"):
        restore_backup(backup_dir, target_home)
    assert not target_home.exists()


def test_restore_detects_manifest_count_tampering_before_writing(tmp_path: Path) -> None:
    source_home = tmp_path / "source"
    _seed_home(source_home)
    backup_dir = create_backup(source_home, tmp_path / "backups")
    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["counts"]["messages"] = 4
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    target_home = tmp_path / "restored"

    with pytest.raises(BackupError, match="backup_integrity_failed"):
        restore_backup(backup_dir, target_home)
    assert not target_home.exists()


def test_restore_detects_omitted_attachment_hash_before_writing(tmp_path: Path) -> None:
    source_home = tmp_path / "source"
    _seed_home(source_home)
    backup_dir = create_backup(source_home, tmp_path / "backups")
    manifest_path = backup_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["files"]["attachments/stored.bin"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    target_home = tmp_path / "restored"

    with pytest.raises(BackupError, match="backup_integrity_failed"):
        restore_backup(backup_dir, target_home)
    assert not target_home.exists()


def test_restore_does_not_overwrite_existing_database(tmp_path: Path) -> None:
    source_home = tmp_path / "source"
    _seed_home(source_home)
    backup_dir = create_backup(source_home, tmp_path / "backups")
    target_home = tmp_path / "restored"
    target_home.mkdir()
    existing_db = target_home / "relayforge.db"
    existing_db.write_bytes(b"preserve")

    with pytest.raises(BackupError, match="restore_target_not_empty"):
        restore_backup(backup_dir, target_home)
    assert existing_db.read_bytes() == b"preserve"
