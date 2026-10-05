from __future__ import annotations

from relayforge.core.states import JobStatus
from relayforge.db.models import Job, utc_now


def test_transient_failure_waits_for_persisted_retry_time(app) -> None:
    service = app.state.jobs
    job, _ = service.create_job("Retry", "Temporary network error", "retry-persist")
    service.transition(job["id"], JobStatus.PREPARING)
    service.transition(job["id"], JobStatus.PLANNING)
    service.set_step(job["id"], "RUNNING", started_at=utc_now())
    assert service.schedule_retry(job["id"], "2999-01-01T00:00:00Z", "network")
    waiting = service.get_job(job["id"])
    assert waiting is not None
    assert waiting["status"] == JobStatus.WAITING_RETRY.value
    assert waiting["retry_at"] == "2999-01-01T00:00:00Z"
    assert waiting["retry_count"] == 1
    assert service.retry_job_ids() == []
    with app.state.jobs.sessions.begin() as session:
        row = session.get(Job, job["id"])
        assert row is not None
        row.retry_at = "2000-01-01T00:00:00Z"
    assert service.retry_job_ids() == [job["id"]]
    assert service.requeue_retry(job["id"])
    assert service.get_job(job["id"])["status"] == JobStatus.QUEUED.value


def test_resume_endpoint_only_requeues_interrupted_job(client, app) -> None:
    service = app.state.jobs
    job, _ = service.create_job("Resume", "Resume after restart", "resume-api")
    service.transition(job["id"], JobStatus.PREPARING)
    service.transition(job["id"], JobStatus.PLANNING)
    service.set_step(job["id"], "INTERRUPTED", finished_at=utc_now())
    service.transition(job["id"], JobStatus.INTERRUPTED)

    response = client.post(f"/api/jobs/{job['id']}/resume", json={"mode": "retry_step"})
    assert response.status_code == 200
    assert response.json()["status"] == JobStatus.QUEUED.value
    assert client.post(f"/api/jobs/{job['id']}/resume", json={"mode": "retry_step"}).status_code == 409


def test_agent_health_api_returns_sanitized_status(client, app) -> None:
    app.state.agent_health.record_failure("codex", "rate_limited", "2026-10-04T00:01:00Z")
    response = client.get("/api/agents")
    assert response.status_code == 200
    assert response.json() == [
        {
            "agent": "codex",
            "status": "RATE_LIMITED",
            "checked_at": response.json()[0]["checked_at"],
            "detail": "rate_limited",
            "rate_limited_until": "2026-10-04T00:01:00Z",
        }
    ]
