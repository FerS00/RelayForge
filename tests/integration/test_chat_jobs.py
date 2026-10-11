import json
import time

from relayforge.adapters.base import NormalizedEvent


class DevelopmentChat:
    def __init__(self, repository):
        self.repository = repository

    async def chat(self, context, prompt):
        action = (
            None
            if "Resultado de herramienta" in prompt
            else {
                "kind": "development_job",
                "repository_id": self.repository,
                "request": "Implementar cambio pequeño, sin commit ni remoto",
            }
        )
        yield NormalizedEvent(
            "agent.message",
            "codex",
            context.step_id,
            {"text": json.dumps({"response": "Prepararé el plan", "action": action})},
        )
        yield NormalizedEvent("agent.exit", "codex", context.step_id, {"outcome": "ok"})


def test_natural_request_creates_two_jobs_in_same_chat_without_mutating_session(client, app):
    repo = client.post("/api/repos", json={"mode": "create", "name": "chat-project"}).json()["repository"]
    import subprocess

    subprocess.run(
        ["git", "-C", repo["path"], "remote", "add", "origin", "https://example.invalid/review-only.git"],
        check=True,
        capture_output=True,
    )
    base = subprocess.check_output(["git", "-C", repo["path"], "rev-parse", "HEAD"]).strip()
    app.state.chat.orchestrators["codex"] = DevelopmentChat(repo["id"])
    cid = client.post("/api/conversations", json={"agent": "codex", "model": "fixture-chat"}).json()["id"]
    url = f"/api/conversations/{cid}/messages"
    for key in ("job-one", "job-two"):
        assert (
            client.post(
                url, json={"content": "Mejora el proyecto"}, headers={"Idempotency-Key": key}
            ).status_code
            == 202
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            data = client.get(url).json()
            expected = 1 if key == "job-one" else 2
            if (
                len(data["jobs"]) == expected
                and not data["active_step"]
                and all(job["status"] == "WAITING_APPROVAL" for job in data["jobs"])
            ):
                break
            time.sleep(0.03)
        assert len(data["jobs"]) == expected
        assert all(job["status"] == "WAITING_APPROVAL" for job in data["jobs"])
    with app.state.engine.connect() as connection:
        session = connection.exec_driver_sql(
            "SELECT session_id FROM conversations WHERE id=?", (cid,)
        ).scalar()
        jobs = connection.exec_driver_sql(
            "SELECT orchestrator_session_id, origin_message_id, origin_turn_id "
            "FROM jobs WHERE conversation_id=?",
            (cid,),
        ).all()
        assert len({job[0] for job in jobs}) == 2 and session not in {job[0] for job in jobs}
        assert all(job[1] and job[2] for job in jobs)
    for job in data["jobs"]:
        assert job["conversation_id"] == cid and job["planning_agent"] == "codex"
        assert job["plan"] and job["approval_kind"] == "plan"
    approvals = client.get("/api/approvals").json()
    first = next(approval for approval in approvals if approval["job_id"] == data["jobs"][0]["id"])
    assert (
        client.post(
            f"/api/approvals/{first['id']}/decision",
            json={"decision": "approve", "scope": "once"},
            headers={"Idempotency-Key": "approve-plan"},
        ).status_code
        == 200
    )
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{first['job_id']}").json()
        if job["status"] == "COMPLETED":
            break
        time.sleep(0.03)
    assert job["status"] == "COMPLETED"
    assert any(event["type"] == "audit.result" for event in job["events"])

    assert job["review_only"]
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        final = client.get(url).json()
        if not final["active_step"] and any(
            "Resultado de herramienta (Job" in message["content"] for message in final["messages"]
        ):
            break
        time.sleep(0.03)
    assert any("Resultado de herramienta (Job" in message["content"] for message in final["messages"])
    assert final["messages"][-1]["role"] == "orchestrator"
    assert subprocess.check_output(["git", "-C", job["worktree_path"], "rev-parse", "HEAD"]).strip() == base
    assert not any(row["job_id"] == job["id"] for row in client.get("/api/approvals").json())
