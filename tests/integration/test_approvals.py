from sqlalchemy.orm import Session

from relayforge.db.models import Conversation, Job


def test_approval_list_and_decision_are_idempotent(client, app) -> None:
    with Session(app.state.engine) as session, session.begin():
        session.add(
            Conversation(
                id="approval-conversation",
                title="Approval",
                workspace_dir="/repo",
                orchestrator="claude",
                session_id="approval-session",
            )
        )
        session.add(
            Job(
                id="approval-job",
                number=987,
                title="Approval job",
                request_text="request",
                conversation_id="approval-conversation",
                status="FINAL_REVIEW",
            )
        )
    approval = app.state.approvals.request(
        "approval-job",
        {"operation": "git.push", "branch": "agent/job-987", "paths": ["src/a.py"]},
        "d" * 64,
        "api-request-987",
    )
    listed = client.get("/api/approvals?status=pending")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == approval["id"]
    app.state.job_scheduler.resume_delivery = lambda _job_id: None
    headers = {"Idempotency-Key": "api-decision-987"}
    first = client.post(
        f"/api/approvals/{approval['id']}/decision",
        json={"decision": "approve", "scope": "once"},
        headers=headers,
    )
    repeated = client.post(
        f"/api/approvals/{approval['id']}/decision",
        json={"decision": "approve", "scope": "once"},
        headers=headers,
    )
    conflict = client.post(
        f"/api/approvals/{approval['id']}/decision",
        json={"decision": "reject", "scope": "once"},
        headers={"Idempotency-Key": "different-decision"},
    )
    assert first.status_code == repeated.status_code == 200
    assert first.json()["decision"] == repeated.json()["decision"] == "approve"
    assert conflict.status_code == 409
