import subprocess
from pathlib import Path

from fastapi.testclient import TestClient


def test_repository_create_and_register(client: TestClient, app) -> None:
    created = client.post("/api/repos", json={"mode": "create", "name": "created"})
    assert created.status_code == 201
    created_repo = created.json()["repository"]
    assert Path(created_repo["path"]).parent == app.state.settings.projects_root
    assert client.get("/api/repos").json()[0]["name"] == "created"

    source = Path(created_repo["path"]).parent / "external"
    source.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main", str(source)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@localhost",
            "commit",
            "--allow-empty",
            "-m",
            "init",
        ],
        check=True,
        capture_output=True,
    )
    registered = client.post(
        "/api/repos", json={"mode": "register", "name": "registered", "path": str(source)}
    )
    assert registered.status_code == 201
    assert registered.json()["repository"]["default_branch"] == "main"
    assert client.post("/api/repos", json={"mode": "create", "name": "../escape"}).status_code == 409


def test_repository_check_commands_are_validated_and_persisted(client: TestClient) -> None:
    invalid = client.post(
        "/api/repos",
        json={
            "mode": "create",
            "name": "unsafe-check",
            "check_commands": [{"name": "shell", "argv": ["cmd.exe", "/c", "whoami"]}],
        },
    )
    assert invalid.status_code == 422
    created = client.post(
        "/api/repos",
        json={
            "mode": "create",
            "name": "declared-check",
            "check_commands": [{"name": "pytest", "argv": ["uv", "run", "pytest", "-q"]}],
        },
    )
    assert created.status_code == 201
    assert created.json()["repository"]["check_commands"] == [
        {"name": "pytest", "argv": ["uv", "run", "pytest", "-q"], "timeout_seconds": 600}
    ]
