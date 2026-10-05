from __future__ import annotations

import time

from fastapi.testclient import TestClient


def _wait(client: TestClient, job_id: str, status: str, timeout: float = 8) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = client.get(f"/api/jobs/{job_id}").json()
        if value.get("status") == status:
            return value
        time.sleep(0.02)
    raise AssertionError(f"Job {job_id} did not reach {status}")


def _repository(client: TestClient, name: str) -> str:
    response = client.post("/api/repos", json={"mode": "create", "name": name})
    assert response.status_code == 201
    return response.json()["repository"]["id"]


def test_trivial_workflow_skips_auditor(client: TestClient, app) -> None:
    repository_id = _repository(client, "trivial-workflow")
    created = client.post(
        "/api/jobs",
        headers={"Idempotency-Key": "workflow-trivial"},
        json={"request_text": "Small change", "repository_id": repository_id, "workflow": "trivial"},
    ).json()["job"]
    result = _wait(client, created["id"], "COMPLETED")
    assert result["workflow"] == "trivial"
    assert app.state.job_scheduler.audit.auditor.profiles == []


def test_auth_path_escalates_to_security_profile(client: TestClient, app, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CODEX_CHANGED_PATH", "src/auth/session.py")
    repository_id = _repository(client, "security-escalation")
    created = client.post(
        "/api/jobs",
        headers={"Idempotency-Key": "workflow-auth-path"},
        json={
            "request_text": "Change a session check",
            "repository_id": repository_id,
            "workflow": "trivial",
        },
    ).json()["job"]
    result = _wait(client, created["id"], "COMPLETED")
    assert result["workflow"] == "security"
    assert app.state.job_scheduler.audit.auditor.profiles == ["security"]


def test_security_plan_waits_for_approval_before_implementation(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_SUGGESTED_WORKFLOW", "security")
    repository_id = _repository(client, "security-approval")
    created = client.post(
        "/api/jobs",
        headers={"Idempotency-Key": "workflow-security-plan"},
        json={
            "request_text": "Review authentication",
            "repository_id": repository_id,
            "workflow": "auto",
        },
    ).json()["job"]
    waiting = _wait(client, created["id"], "WAITING_APPROVAL")
    assert waiting["approval_kind"] == "plan"
    assert waiting["workflow"] == "security"
    assert waiting["diff_paths"] == []
    approval = next(item for item in client.get("/api/approvals").json() if item["job_id"] == created["id"])
    decision = client.post(
        f"/api/approvals/{approval['id']}/decision",
        headers={"Idempotency-Key": "approve-security-plan"},
        json={"decision": "approve", "scope": "once"},
    )
    assert decision.status_code == 200
    result = _wait(client, created["id"], "COMPLETED")
    assert result["workflow"] == "security"
