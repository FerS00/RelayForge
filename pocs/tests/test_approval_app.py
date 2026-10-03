from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from poc08_approval.app import create_app


def test_approval_flow_survives_app_restart_and_is_idempotent(tmp_path: Path) -> None:
    database, effects_dir = tmp_path / "approvals.sqlite", tmp_path / "effects"
    first = TestClient(create_app(database, effects_dir))
    created = first.post("/jobs", json={"operation": "git.push"}).json()
    approval_id, job_id = created["approval_id"], created["id"]
    assert created["status"] == "WAITING_APPROVAL"

    second = TestClient(create_app(database, effects_dir))
    assert second.get("/approvals", params={"status": "pending"}).json()[0]["id"] == approval_id
    path = f"/approvals/{approval_id}/decision"
    payload = {"decision": "approve", "scope": "job"}
    headers = {"Idempotency-Key": "K1"}
    decision = second.post(path, json=payload, headers=headers)
    assert decision.status_code == 200
    assert decision.json()["effect_count"] == 1
    assert second.post(path, json=payload, headers=headers).json() == decision.json()
    assert len(second.get("/effects").json()) == 1
    assert second.post(path, json=payload, headers={"Idempotency-Key": "K2"}).status_code == 409
    auto = second.post(f"/jobs/{job_id}/request", json={"operation": "git.push"})
    assert auto.json()["status"] == "approved"
    assert auto.json()["decided_via"] == "grant"
    assert second.get("/jobs/unknown").status_code == 404

    other = second.post("/jobs", json={"operation": "git.push"}).json()
    assert second.get(f"/approvals/{other['approval_id']}").status_code == 404
    pending = second.get("/approvals", params={"status": "pending"}).json()
    assert any(item["id"] == other["approval_id"] for item in pending)
    rejected = second.post(f"/approvals/{other['approval_id']}/decision",
                           json={"decision": "reject", "scope": "once"},
                           headers={"Idempotency-Key": "K3"})
    assert rejected.json()["job_status"] == "FAILED"
    assert len(second.get("/effects").json()) == 2
    assert len(list(effects_dir.glob("*.txt"))) == 2
