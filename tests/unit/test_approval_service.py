import pytest
from sqlalchemy.orm import sessionmaker

from relayforge.core.approvals import ApprovalConflict, ApprovalService
from relayforge.db.models import Base, Conversation, Job
from relayforge.db.session import create_db_engine


@pytest.fixture
def approval_service(tmp_path):
    engine = create_db_engine(tmp_path / "approvals.db")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions.begin() as session:
        session.add_all(
            [
                Conversation(
                    id="c1", title="one", workspace_dir="/repo", orchestrator="claude", session_id="s1"
                ),
                Conversation(
                    id="c2", title="two", workspace_dir="/repo", orchestrator="claude", session_id="s2"
                ),
            ]
        )
        session.add_all(
            [
                Job(
                    id="j1",
                    number=1,
                    title="one",
                    request_text="r",
                    conversation_id="c1",
                    status="FINAL_REVIEW",
                ),
                Job(
                    id="j2",
                    number=2,
                    title="two",
                    request_text="r",
                    conversation_id="c2",
                    status="FINAL_REVIEW",
                ),
            ]
        )
    service = ApprovalService(sessions)
    yield service
    engine.dispose()


def test_approval_is_idempotent_and_grant_stays_bound_to_job(approval_service: ApprovalService) -> None:
    operation = {"operation": "git.push", "branch": "agent/job-1"}
    row = approval_service.request("j1", operation, "a" * 64, "request-j1")
    decision = approval_service.decide(
        row["id"], decision="approve", scope="job", reason=None, idempotency_key="decision-j1"
    )
    repeated = approval_service.decide(
        row["id"], decision="approve", scope="job", reason=None, idempotency_key="decision-j1"
    )
    assert repeated["id"] == decision["id"]
    assert approval_service.is_approved("j1", operation, "a" * 64)
    assert not approval_service.is_approved("j2", operation, "a" * 64)
    assert approval_service.grant_allows("j1", operation)
    assert not approval_service.grant_allows("j2", operation)
    assert not approval_service.grant_allows("j1", {**operation, "branch": "agent/job-2"})
    with pytest.raises(ApprovalConflict):
        approval_service.request("j1", operation, "c" * 64, "request-j1")


def test_deny_cannot_be_approved_and_second_decision_conflicts(approval_service: ApprovalService) -> None:
    row = approval_service.request("j1", {"operation": "git.push"}, "b" * 64, "request-deny")
    with pytest.raises(ApprovalConflict):
        approval_service.decide(
            row["id"],
            decision="approve",
            scope="once",
            reason=None,
            idempotency_key="denied",
            policy_decision="deny",
        )
    approval_service.decide(row["id"], decision="reject", scope="once", reason="no", idempotency_key="reject")
    with pytest.raises(ApprovalConflict):
        approval_service.decide(
            row["id"], decision="approve", scope="once", reason=None, idempotency_key="approve"
        )
