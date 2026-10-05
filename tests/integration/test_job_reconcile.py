from relayforge.core.states import JobStatus


def test_startup_reconciliation_interrupts_active_jobs(app) -> None:
    service = app.state.jobs
    job, _ = service.create_job("Interrupted", "Plan this request", "reconcile-key")
    service.transition(job["id"], JobStatus.PREPARING)
    service.transition(job["id"], JobStatus.PLANNING)
    service.set_step(job["id"], "RUNNING")
    service.reconcile_active_jobs()
    result = service.get_job(job["id"])
    assert result is not None
    assert result["status"] == JobStatus.INTERRUPTED.value
    assert result["steps"][0]["status"] == "INTERRUPTED"
