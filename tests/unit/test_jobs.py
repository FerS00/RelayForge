from pathlib import Path

import pytest

from relayforge.adapters.base import PlanResult, TriageResult
from relayforge.core.events import EventBus
from relayforge.core.jobs import JobService, VersionConflict
from relayforge.core.states import InvalidTransition, JobStatus
from relayforge.db.session import create_db_engine, make_session_factory, run_migrations


class UnusedOrchestrator:
    name = "unused"

    async def plan(self, ctx, request_text):
        raise AssertionError("orchestrator must not be called")

    async def triage(self, ctx, findings, diff, test_results) -> TriageResult:
        raise AssertionError("triage must not be called")

    def chat(self, ctx, message):
        raise AssertionError("chat must not be called")


@pytest.fixture
def job_service(tmp_path: Path) -> JobService:
    db_path = tmp_path / "jobs.db"
    run_migrations(db_path)
    engine = create_db_engine(db_path)
    service = JobService(
        make_session_factory(engine), EventBus(), UnusedOrchestrator(), tmp_path, tmp_path / "data"
    )
    try:
        yield service
    finally:
        engine.dispose()


def test_job_transitions_persist_with_versioned_events(job_service: JobService) -> None:
    created, is_new = job_service.create_job("Test", "Implement a test plan", "key-1")
    assert is_new
    assert created["display_id"] == "JOB-000001"
    job_service.transition(created["id"], JobStatus.PREPARING, expected_version=0)
    current = job_service.transition(created["id"], JobStatus.PLANNING, expected_version=1)
    assert current["status"] == JobStatus.PLANNING.value
    assert current["version"] == 2
    with pytest.raises(InvalidTransition):
        job_service.transition(created["id"], JobStatus.PREPARING)
    with pytest.raises(VersionConflict):
        job_service.transition(created["id"], JobStatus.COMPLETED, expected_version=0)
    conversation_id, events = job_service.get_events(created["id"], 0)
    assert conversation_id == created["conversation_id"]
    assert [event.data["to"] for event in events] == ["QUEUED", "PREPARING", "PLANNING"]


def test_idempotency_returns_existing_job_without_duplicate_rows(job_service: JobService) -> None:
    first, created = job_service.create_job(None, "Plan this", "same-key")
    second, replayed = job_service.create_job(None, "Different text", "same-key")
    assert created and not replayed
    assert first["id"] == second["id"]
    assert len(job_service.list_jobs()) == 1


def test_completed_plan_is_serialized_for_job_detail(job_service: JobService) -> None:
    job, _ = job_service.create_job("Plan", "Request", "plan-key")
    job_service.transition(job["id"], JobStatus.PREPARING)
    job_service.transition(job["id"], JobStatus.PLANNING)
    plan = PlanResult("Objective", "Summary", ("Step one",), ("Risk one",))
    job_service.complete_plan(job["id"], plan)
    job_service.transition(job["id"], JobStatus.COMPLETED)
    detail = job_service.get_job(job["id"])
    assert detail is not None
    assert detail["plan"] == {
        "objective": "Objective",
        "summary": "Summary",
        "steps": ["Step one"],
        "risks": ["Risk one"],
        "suggested_workflow": "feature",
    }
