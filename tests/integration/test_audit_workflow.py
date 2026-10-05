from __future__ import annotations

import time

from fastapi.testclient import TestClient
from sqlalchemy import text

from relayforge.adapters.base import AuditResult, FindingInput, TriageDecision, TriageResult


class ScriptedAuditor:
    name = "scripted-auditor"

    def __init__(self, results: list[AuditResult]) -> None:
        self.results = iter(results)

    async def audit(
        self, worktree, changed_paths, commands, iteration, diff_text="", profile="default"
    ) -> AuditResult:
        return next(self.results)


def _wait(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        detail = client.get(f"/api/jobs/{job_id}").json()
        if detail["status"] in {"COMPLETED", "FAILED", "WAITING_APPROVAL"}:
            return detail
        time.sleep(0.05)
    raise AssertionError("Job did not reach a terminal or approval state")


def _finding() -> FindingInput:
    return FindingInput(
        "AG-1",
        "Medio",
        "fake-implementation.txt",
        1,
        "Fixture finding",
        "The first line needs review.",
        "Update the line.",
    )


def test_accepted_finding_is_triaged_fixed_and_reaudited(client: TestClient, app, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CODEX_SCENARIO", "success")
    app.state.job_scheduler.audit.auditor = ScriptedAuditor(
        [
            AuditResult(
                "REJECTED",
                "One finding",
                (_finding(),),
                {"fake-implementation.txt": "before"},
                {"fake-implementation.txt": "before"},
            ),
            AuditResult(
                "APPROVED",
                "Clean after revision",
                (),
                {"fake-implementation.txt": "after"},
                {"fake-implementation.txt": "after"},
            ),
        ]
    )

    async def accept(ctx, findings, diff, test_results) -> TriageResult:
        return TriageResult(
            tuple(
                TriageDecision(str(item["id"]), "accept", "Affects the requested behavior.")
                for item in findings
            )
        )

    monkeypatch.setattr(app.state.jobs.orchestrator, "triage", accept)
    repository = client.post("/api/repos", json={"mode": "create", "name": "audit-loop"}).json()["repository"]
    created = client.post(
        "/api/jobs",
        headers={"Idempotency-Key": "audit-loop"},
        json={"request_text": "Create and revise a fixture", "repository_id": repository["id"]},
    ).json()["job"]
    detail = _wait(client, created["id"])
    assert detail["status"] == "COMPLETED"
    assert detail["iteration"] == 2
    assert detail["findings"][0]["triage_decision"] == "accept"
    assert detail["findings"][0]["fixed_in_iteration"] == 2
    assert [step["kind"] for step in detail["steps"]].count("audit") == 2
    assert any(step["kind"] == "triage" and step["status"] == "SUCCEEDED" for step in detail["steps"])


def test_blocked_audit_fails_instead_of_completing(client: TestClient, app, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CODEX_SCENARIO", "success")
    app.state.job_scheduler.audit.auditor = ScriptedAuditor(
        [AuditResult("BLOCKED", "Hash mismatch", (), {"x": "before"}, {"x": "after"})]
    )
    repository = client.post("/api/repos", json={"mode": "create", "name": "blocked-audit"}).json()[
        "repository"
    ]
    created = client.post(
        "/api/jobs",
        headers={"Idempotency-Key": "blocked-audit"},
        json={"request_text": "Create fixture", "repository_id": repository["id"]},
    ).json()["job"]
    detail = _wait(client, created["id"])
    assert detail["status"] == "FAILED"
    assert detail["error_code"] == "audit_blocked"


def test_iteration_limit_waits_for_human_approval(client: TestClient, app, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_CODEX_SCENARIO", "success")
    app.state.job_scheduler.audit.auditor = ScriptedAuditor(
        [AuditResult("REJECTED", "Still needs a change", (_finding(),), {}, {})]
    )

    async def accept(ctx, findings, diff, test_results) -> TriageResult:
        return TriageResult(
            tuple(TriageDecision(str(item["id"]), "accept", "Confirmed.") for item in findings)
        )

    monkeypatch.setattr(app.state.jobs.orchestrator, "triage", accept)
    repository = client.post("/api/repos", json={"mode": "create", "name": "audit-limit"}).json()[
        "repository"
    ]
    original_create = app.state.jobs.create_job

    def create_limited_job(*args, **kwargs):
        created, fresh = original_create(*args, **kwargs)
        with app.state.engine.begin() as connection:
            connection.execute(
                text("UPDATE jobs SET max_iterations = 1 WHERE id = :id"), {"id": created["id"]}
            )
        return created, fresh

    monkeypatch.setattr(app.state.jobs, "create_job", create_limited_job)
    created = client.post(
        "/api/jobs",
        headers={"Idempotency-Key": "iteration-limit"},
        json={"request_text": "Create fixture", "repository_id": repository["id"]},
    ).json()["job"]
    detail = _wait(client, created["id"])
    assert detail["status"] == "WAITING_APPROVAL"
    assert detail["approval_kind"] == "iteration_limit"
