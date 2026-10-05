from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


def wait_for(client, app, job_id: str, status: str) -> dict:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        task = app.state.job_scheduler._tasks.get(job_id)
        if job["status"] == status and (task is None or task.done()):
            return job
        time.sleep(0.03)
    raise AssertionError(f"Expected {status}; received {job}")


@pytest.mark.parametrize(
    "failure,code", [("429 insufficient_quota", "rate_limited"), ("OAuth token expired", "auth_required")]
)
def test_claude_handoff_preserves_worktree_and_requires_plan_approval(
    client, app, monkeypatch, failure, code
):
    repository = client.post("/api/repos", json={"mode": "create", "name": "handoff-project"}).json()[
        "repository"
    ]
    monkeypatch.setenv("FAKE_PLAN_FAILURE", failure)
    created = client.post(
        "/api/jobs",
        json={
            "request_text": "Implement a small change",
            "repository_id": repository["id"],
            "agent": "claude",
            "model": "fixture-claude",
            "require_plan_approval": True,
        },
        headers={"Idempotency-Key": "operational-handoff"},
    )
    assert created.status_code == 202
    job_id = created.json()["job"]["id"]
    paused = wait_for(client, app, job_id, "WAITING_AGENT")
    assert paused["error_code"] == code
    assert paused["paused_stage"] == "plan"
    worktree = Path(paused["worktree_path"])
    assert worktree.is_dir()
    assert not (worktree / "fake-implementation.txt").exists()
    bad_role = client.post(
        f"/api/jobs/{job_id}/step", json={"agent": "antigravity", "version": paused["version"]}
    )
    stale = client.post(f"/api/jobs/{job_id}/step", json={"agent": "codex", "version": paused["version"] - 1})
    assert bad_role.status_code == stale.status_code == 409
    switched = client.post(
        f"/api/jobs/{job_id}/step",
        json={"agent": "codex", "model": "fixture-codex", "version": paused["version"]},
    )
    assert switched.status_code == 200
    planned = wait_for(client, app, job_id, "WAITING_APPROVAL")
    assert planned["worktree_path"] == paused["worktree_path"]
    assert planned["branch"] == paused["branch"]
    assert planned["planning_agent"] == "codex"
    assert planned["planning_model"] == "fixture-codex"
    assert planned["approval_kind"] == "plan"
    assert not (worktree / "fake-implementation.txt").exists()
    assert any(
        event["type"] == "agent.selected" and event["data"]["reason"] == code for event in planned["events"]
    )
    step = next(step for step in planned["steps"] if step["kind"] == "plan")
    output = app.state.settings.home / "data" / "jobs" / step["id"] / "codex-plan.ndjson"
    argv = json.loads(output.read_text(encoding="utf-8").splitlines()[0])["argv"]
    assert argv[argv.index("-s") + 1] == "read-only"
    assert argv[argv.index("--model") + 1] == "fixture-codex"
    assert client.get(f"/api/jobs?repository_id={repository['id']}").json()[0]["id"] == job_id
    assert client.get("/api/jobs?repository_id=unknown").json() == []
    selected = client.post(
        f"/api/jobs/{job_id}/step",
        json={"agent": "codex", "model": "fixture-implementation", "version": planned["version"]},
    )
    assert selected.status_code == 200
    assert selected.json()["status"] == "WAITING_APPROVAL"
    assert selected.json()["implementation_model"] == "fixture-implementation"
    approval = next(
        row for row in client.get("/api/approvals?status=pending").json() if row["job_id"] == job_id
    )
    decision = client.post(
        f"/api/approvals/{approval['id']}/decision",
        json={"decision": "approve", "scope": "once"},
        headers={"Idempotency-Key": "operational-plan-approve"},
    )
    assert decision.status_code == 200
    implemented = wait_for(client, app, job_id, "COMPLETED")
    assert any(event["type"] == "final_review.created" for event in implemented["events"])
    assert implemented["worktree_path"] == paused["worktree_path"]
    assert (worktree / "fake-implementation.txt").exists()
    assert implemented["codex_thread_id"] == "fake-thread-001"


def test_agent_status_exposes_only_safe_probes_and_measured_usage(client, app, monkeypatch):
    from relayforge.api.routes import agents

    monkeypatch.setattr(
        agents, "_agent", lambda *_args: {"status": "AVAILABLE", "version": "1.2.3", "auth": "UNKNOWN"}
    )
    created = client.post(
        "/api/jobs",
        json={"request_text": "Plan with Codex", "agent": "codex", "model": "fixture-model"},
        headers={"Idempotency-Key": "operational-usage"},
    )
    job_id = created.json()["job"]["id"]
    wait_for(client, app, job_id, "COMPLETED")
    response = client.get("/api/agents/status")
    assert response.status_code == 200
    rows = {row["agent"]: row for row in response.json()}
    assert set(rows) == {"claude", "codex", "antigravity"}
    assert rows["codex"]["usage"]["turns"] == 1
    assert rows["codex"]["usage"]["input_tokens"] == 10
    assert rows["codex"]["usage"]["output_tokens"] == 5
    assert rows["codex"]["usage"]["five_hour"] == {"status": "unknown", "remaining": None}
    assert rows["codex"]["usage"]["weekly"]["status"] == "unknown"
    assert rows["antigravity"]["auth"] == "UNKNOWN"
    assert rows["claude"]["usage"]["input_tokens"] is None


def test_triage_handoff_does_not_repeat_implementation_or_old_audit(client, app, monkeypatch):
    from relayforge.adapters.base import AuditResult, FindingInput

    class Auditor:
        calls = 0

        async def audit(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return AuditResult(
                    "REJECTED",
                    "Fixture finding",
                    (
                        FindingInput(
                            "fixture", "Medio", "fake-implementation.txt", 1, "Fix", "Fixture", "Fix fixture"
                        ),
                    ),
                    {},
                    {},
                )
            return AuditResult("APPROVED", "Fixture approved", (), {}, {})

    async def fail_triage(*args, **kwargs):
        raise RuntimeError("auth_required")

    auditor = Auditor()
    app.state.job_scheduler.audit.auditor = auditor
    monkeypatch.setattr(app.state.jobs.orchestrator, "triage", fail_triage)
    repository = client.post("/api/repos", json={"mode": "create", "name": "triage-project"}).json()[
        "repository"
    ]
    created = client.post(
        "/api/jobs",
        json={"request_text": "Implement fixture", "repository_id": repository["id"], "workflow": "feature"},
        headers={"Idempotency-Key": "triage-handoff"},
    )
    job_id = created.json()["job"]["id"]
    paused = wait_for(client, app, job_id, "WAITING_AGENT")
    assert paused["paused_stage"] == "triage"
    assert auditor.calls == 1
    switched = client.post(f"/api/jobs/{job_id}/step", json={"agent": "codex", "version": paused["version"]})
    assert switched.status_code == 200
    finished = wait_for(client, app, job_id, "COMPLETED")
    assert auditor.calls == 2
    assert finished["iteration"] == 2
    assert finished["worktree_path"] == paused["worktree_path"]
    assert len([event for event in finished["events"] if event["type"] == "implementation.completed"]) == 2
    assert any(
        step["kind"] == "triage" and step["agent"] == "codex" and step["status"] == "SUCCEEDED"
        for step in finished["steps"]
    )
