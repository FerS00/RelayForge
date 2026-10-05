from __future__ import annotations

import time

import psutil
from fastapi.testclient import TestClient


def _job(client: TestClient, name: str, check: dict[str, object]) -> dict[str, object]:
    repository = client.post(
        "/api/repos",
        json={"mode": "create", "name": name, "check_commands": [check]},
    )
    assert repository.status_code == 201, repository.text
    created = client.post(
        "/api/jobs",
        headers={"Idempotency-Key": f"check-{name}"},
        json={"request_text": "Implement fixture", "repository_id": repository.json()["repository"]["id"]},
    )
    assert created.status_code == 202, created.text
    return created.json()["job"]


def _wait(client: TestClient, job_id: str) -> dict[str, object]:
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        detail = client.get(f"/api/jobs/{job_id}").json()
        if detail["status"] in {"COMPLETED", "FAILED"}:
            return detail
        time.sleep(0.05)
    raise AssertionError(f"Job {job_id} no terminó.")


def test_check_passes_persists_counts_and_omits_agent_environment(
    client: TestClient, app, monkeypatch
) -> None:
    import sys
    from pathlib import Path

    monkeypatch.setenv("FAKE_CODEX_SCENARIO", "success")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-secret")
    monkeypatch.setenv("CODEX_HOME", "synthetic-private-home")
    fake = Path(__file__).resolve().parents[1] / "fakes" / "fake_check.py"
    job = _job(
        client,
        "check-pass",
        {"name": "pytest-fixture", "argv": [sys.executable, str(fake), "pass"], "timeout_seconds": 5},
    )
    detail = _wait(client, str(job["id"]))
    assert detail["status"] == "COMPLETED"
    result = next(event for event in detail["events"] if event["type"] == "checks.result")
    assert result["data"]["status"] == "passed"
    assert result["data"]["counts"] == {"passed": 2, "failed": 0, "skipped": 1}
    assert "ANTHROPIC_API_KEY" not in str(result)
    step = next(step for step in detail["steps"] if step["kind"] == "checks")
    assert step["status"] == "SUCCEEDED"
    assert any(event["data"].get("to") == "TESTING" for event in detail["events"])


def test_check_failure_fails_job_without_retry(client: TestClient, monkeypatch) -> None:
    import sys
    from pathlib import Path

    monkeypatch.setenv("FAKE_CODEX_SCENARIO", "success")
    fake = Path(__file__).resolve().parents[1] / "fakes" / "fake_check.py"
    job = _job(client, "check-fail", {"name": "failing", "argv": [sys.executable, str(fake), "fail"]})
    detail = _wait(client, str(job["id"]))
    assert detail["status"] == "FAILED"
    assert detail["error_code"] == "checks_failed"
    assert len([event for event in detail["events"] if event["type"] == "checks.result"]) == 1
    step = next(step for step in detail["steps"] if step["kind"] == "checks")
    assert step["status"] == "FAILED"
    assert step["error_code"] == "checks_failed"


def test_check_timeout_kills_child_process(client: TestClient, app, monkeypatch) -> None:
    import sys
    from pathlib import Path

    monkeypatch.setenv("FAKE_CODEX_SCENARIO", "success")
    fake = Path(__file__).resolve().parents[1] / "fakes" / "fake_check.py"
    killed_pids: list[int] = []
    supervisor = app.state.supervisor
    original_kill = supervisor.kill

    def capture_and_kill(handle) -> None:
        try:
            children = psutil.Process(handle.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            children = []
        killed_pids.extend(child.pid for child in children)
        original_kill(handle)

    supervisor.kill = capture_and_kill
    job = _job(
        client,
        "check-timeout",
        {"name": "timeout", "argv": [sys.executable, str(fake), "timeout"], "timeout_seconds": 1},
    )
    detail = _wait(client, str(job["id"]))
    assert detail["status"] == "FAILED"
    event = next(event for event in detail["events"] if event["type"] == "checks.result")
    assert event["data"]["status"] == "timeout"
    assert killed_pids
    assert all(not psutil.pid_exists(pid) for pid in killed_pids)
