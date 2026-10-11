from __future__ import annotations

import io
import zipfile
from pathlib import Path

from relayforge.db.models import Job


def test_files_api_lists_downloads_and_zips_only_deliverables(client, app) -> None:
    conversation = app.state.chat.create_conversation("codex")
    workspace = Path(app.state.settings.workspace_dir)
    (workspace / "src").mkdir()
    (workspace / "src" / "index.html").write_text("<h1>Ready</h1>", encoding="utf-8")
    (workspace / ".env.local").write_text("secret", encoding="utf-8")
    (workspace / ".git").mkdir()
    (workspace / ".git" / "config").write_text("secret", encoding="utf-8")

    roots = client.get(f"/api/conversations/{conversation['id']}/files/roots")
    listing = client.get(f"/api/conversations/{conversation['id']}/files", params={"root": "workspace"})
    content = client.get(
        f"/api/conversations/{conversation['id']}/files/content",
        params={"root": "workspace", "path": "src/index.html"},
    )
    zipped = client.get(
        f"/api/conversations/{conversation['id']}/files/zip",
        params={"root": "workspace", "path": "src"},
    )

    assert roots.json() == {"roots": [{"id": "workspace", "name": "Workspace"}]}
    assert [item["name"] for item in listing.json()["entries"]] == ["src"]
    assert content.content == b"<h1>Ready</h1>"
    assert content.headers["content-disposition"].startswith("attachment;")
    assert content.headers["x-content-type-options"] == "nosniff"
    assert content.headers["content-security-policy"] == "sandbox"
    with zipfile.ZipFile(io.BytesIO(zipped.content)) as archive:
        assert archive.namelist() == ["index.html"]
    assert list((app.state.settings.home / "data" / "tmp").glob("*.zip")) == []


def test_files_api_rejects_traversal_secrets_and_cross_conversation_roots(
    client, app, tmp_path: Path
) -> None:
    conversation = app.state.chat.create_conversation("codex")
    other = app.state.chat.create_conversation("codex")
    workspace = Path(app.state.settings.workspace_dir)
    (workspace / ".env.private").write_text("secret", encoding="utf-8")
    worktree = tmp_path / "linked-job-worktree"
    worktree.mkdir()
    (worktree / "result.txt").write_text("job output", encoding="utf-8")
    job, _ = app.state.jobs.create_job(
        "Deliverable root", "Inspect output", "deliverables-api-job", conversation_id=conversation["id"]
    )
    with app.state.actions.sessions.begin() as session:
        session.get(Job, job["id"]).worktree_path = str(worktree)

    traversal = client.get(
        f"/api/conversations/{conversation['id']}/files",
        params={"root": "workspace", "path": "../outside.txt"},
    )
    secret = client.get(
        f"/api/conversations/{conversation['id']}/files/content",
        params={"root": "workspace", "path": ".env.private"},
    )
    linked_root = client.get(
        f"/api/conversations/{conversation['id']}/files",
        params={"root": f"job:{job['id']}", "path": ""},
    )
    other_root = client.get(
        f"/api/conversations/{other['id']}/files",
        params={"root": f"job:{job['id']}", "path": ""},
    )

    assert traversal.status_code == 400
    assert traversal.json()["error"]["code"] == "path_rejected"
    assert secret.status_code == 404
    assert secret.json()["error"]["code"] == "file_not_found"
    assert [item["name"] for item in linked_root.json()["entries"]] == ["result.txt"]
    assert other_root.status_code == 404
