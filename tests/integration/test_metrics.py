from __future__ import annotations

import json

from sqlalchemy import select

from relayforge.db.models import Finding, Job, JobStep


def test_metrics_summary_matches_five_jobs(client, app) -> None:
    service = app.state.jobs
    jobs = [
        service.create_job(f"metric-{index}", "metrics fixture", f"metric-key-{index}")[0]
        for index in range(5)
    ]
    with service.sessions.begin() as session:
        for index, item in enumerate(jobs):
            row = session.get(Job, item["id"])
            assert row is not None
            row.workflow = "trivial" if index == 4 else "feature"
            row.status = "FAILED" if index >= 3 else "COMPLETED"
            row.created_at = "2026-10-04T00:00:00Z"
            row.finished_at = f"2026-10-04T00:00:{10 + index:02d}Z"
            row.retry_count = 1 if index == 3 else 0
            step = session.scalar(select(JobStep).where(JobStep.job_id == row.id))
            assert step is not None
            step.agent = "codex"
            step.status = "FAILED" if index >= 3 else "SUCCEEDED"
            step.started_at = row.created_at
            step.finished_at = row.finished_at
        first = session.scalar(select(Job).where(Job.id == jobs[0]["id"]))
        assert first is not None
        session.add(
            JobStep(
                id="metrics-check-step",
                job_id=first.id,
                kind="checks",
                agent="core",
                status="SUCCEEDED",
                started_at=first.created_at,
                finished_at=first.finished_at,
                summary_json=json.dumps({"results": [{"status": "passed"}, {"status": "skipped"}]}),
            )
        )
        audit_step = JobStep(
            id="metrics-audit-step",
            job_id=first.id,
            kind="audit",
            agent="antigravity",
            status="SUCCEEDED",
            started_at=first.created_at,
            finished_at=first.finished_at,
        )
        session.add(audit_step)
        session.flush()
        session.add(
            Finding(
                id="metrics-finding",
                job_id=first.id,
                audit_step_id=audit_step.id,
                audit_no=1,
                external_id="metric-finding",
                severity="Medio",
                file="src/example.py",
                line=1,
                title="Finding fixture",
                evidence="Evidence",
                recommendation="Fix it",
            )
        )
    response = client.get("/api/metrics/summary?from=2026-10-03T00:00:00Z&to=2026-10-05T00:00:00Z")
    assert response.status_code == 200
    result = response.json()
    assert result["total_jobs"] == 5
    assert result["jobs_by_status"] == {"COMPLETED": 3, "FAILED": 2}
    assert result["jobs_by_workflow"] == {"feature": 4, "trivial": 1}
    assert result["retry_count"] == 1
    assert result["failed_steps"] == 2
    assert result["step_count"] == 7
    assert result["checks"] == {"passed": 1, "failed": 0, "skipped": 1}
    assert result["findings_by_severity"] == {"Medio": 1}


def test_metrics_rejects_invalid_range(client) -> None:
    assert (
        client.get("/api/metrics/summary?from=2026-10-05T00:00:00Z&to=2026-10-04T00:00:00Z").status_code
        == 422
    )
    assert client.get("/api/metrics/summary?from=2026-10-04").status_code == 422
