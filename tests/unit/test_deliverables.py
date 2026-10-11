from __future__ import annotations

import os
import subprocess
import zipfile
from pathlib import Path

import pytest
from sqlalchemy import select

from relayforge.core.deliverables import (
    DeliverableError,
    Root,
    file_size,
    find_root,
    list_directory,
    read_file,
    resolve,
    roots,
    zip_stream,
)
from relayforge.db.models import Job


@pytest.mark.parametrize(
    "raw",
    [
        "../outside.txt",
        "folder/../../outside.txt",
        "/absolute/file.txt",
        "C:/Windows/win.ini",
        "//server/share/file.txt",
        "folder\\file.txt",
        "file.txt:secret",
        "NUL.txt",
        "folder//file.txt",
        "./file.txt",
        "bad\x00name",
    ],
)
def test_resolve_rejects_unsafe_relative_paths(tmp_path: Path, raw: str) -> None:
    root = Root("workspace", "Workspace", tmp_path)
    with pytest.raises(DeliverableError, match="path_rejected"):
        resolve(root, raw)


def test_root_listing_excludes_secrets_and_sorts_entries(tmp_path: Path) -> None:
    root_path = tmp_path / "workspace"
    root_path.mkdir()
    (root_path / "z.txt").write_text("z", encoding="utf-8")
    (root_path / "A.txt").write_text("a", encoding="utf-8")
    for name in (".git", "node_modules", ".venv", ".codex", ".ssh"):
        (root_path / name).mkdir()
        (root_path / name / "hidden.txt").write_text("secret", encoding="utf-8")
    for name in (".env.local", "token.pem", "id_rsa_backup", "auth.json", ".npmrc"):
        (root_path / name).write_text("secret", encoding="utf-8")

    listing = list_directory(Root("workspace", "Workspace", root_path), "")

    assert [item["name"] for item in listing["entries"]] == ["A.txt", "z.txt"]
    assert listing["truncated"] is False
    for hidden in (".git/hidden.txt", ".env.local", "token.pem", "auth.json"):
        with pytest.raises(DeliverableError, match="file_not_found"):
            resolve(Root("workspace", "Workspace", root_path), hidden)


def test_file_size_and_read_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = tmp_path / "large.txt"
    target.write_bytes(b"12345")
    monkeypatch.setattr("relayforge.core.deliverables.MAX_FILE_BYTES", 4)
    root = Root("workspace", "Workspace", tmp_path)

    with pytest.raises(DeliverableError, match="file_too_large"):
        file_size(root, "large.txt")
    with pytest.raises(DeliverableError, match="file_too_large"):
        read_file(root, "large.txt")


def test_zip_skips_links_and_deletes_temporary_on_limit_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root_path = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root_path.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    (root_path / "visible.txt").write_text("visible", encoding="utf-8")
    link = root_path / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("El host no permite crear symlinks sin elevación.")
    archive_path = zip_stream(Root("workspace", "Workspace", root_path), "", tmp_path / "tmp")
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.namelist() == ["visible.txt"]
    archive_path.unlink()

    (root_path / "second.txt").write_text("second", encoding="utf-8")
    monkeypatch.setattr("relayforge.core.deliverables.MAX_ZIP_FILES", 1)
    with pytest.raises(DeliverableError, match="zip_too_large"):
        zip_stream(Root("workspace", "Workspace", root_path), "", tmp_path / "tmp")
    assert list((tmp_path / "tmp").iterdir()) == []


@pytest.mark.skipif(os.name != "nt", reason="Las junctions son exclusivas de Windows.")
def test_resolve_rejects_junctions_without_following_them(tmp_path: Path) -> None:
    root_path = tmp_path / "workspace"
    outside = tmp_path / "outside"
    root_path.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")
    junction = root_path / "junction"
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(outside)],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    if result.returncode != 0:
        pytest.skip("Windows no permitió crear una junction en el directorio temporal.")

    root = Root("workspace", "Workspace", root_path)
    with pytest.raises(DeliverableError, match="path_rejected"):
        resolve(root, "junction/secret.txt")
    assert all(item["name"] != "junction" for item in list_directory(root, "")["entries"])
    archive = zip_stream(root, "", tmp_path / "tmp")
    with zipfile.ZipFile(archive) as zipped:
        assert "junction/secret.txt" not in zipped.namelist()


def test_roots_include_only_conversation_workspace_and_existing_job_worktrees(app, tmp_path: Path) -> None:
    first = app.state.chat.create_conversation("codex")
    second = app.state.chat.create_conversation("codex")
    first_job, _ = app.state.jobs.create_job(
        "First", "Request", "deliverables-first", conversation_id=first["id"]
    )
    other_job, _ = app.state.jobs.create_job(
        "Other", "Request", "deliverables-other", conversation_id=second["id"]
    )
    worktree = tmp_path / "first-worktree"
    worktree.mkdir()
    with app.state.actions.sessions.begin() as session:
        session.get(Job, first_job["id"]).worktree_path = str(worktree)
        session.get(Job, other_job["id"]).worktree_path = str(tmp_path / "missing-worktree")
    with app.state.actions.sessions() as session:
        available = roots(session, first["id"])
        assert [item.ref for item in available] == ["workspace", f"job:{first_job['id']}"]
        assert find_root(session, first["id"], f"job:{first_job['id']}").path == worktree
        assert session.scalar(select(Job.id).where(Job.id == other_job["id"])) == other_job["id"]
