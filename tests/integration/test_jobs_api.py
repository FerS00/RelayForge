from __future__ import annotations

import asyncio
import json
import time

from fastapi.testclient import TestClient
from starlette.requests import Request

from relayforge.api.routes.jobs import job_events


def _wait_for_job(client: TestClient, job_id: str, status: str, timeout: float = 5) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = client.get(f"/api/jobs/{job_id}").json()
        if result.get("status") == status:
            return result
        time.sleep(0.02)
    raise AssertionError(f"Job {job_id} did not reach {status}")


def test_plan_job_completes_and_is_idempotent(client: TestClient, app) -> None:
    response = client.post(
        "/api/jobs",
        json={"title": "Plan de ejemplo", "request_text": "Propón los pasos de trabajo."},
        headers={"Idempotency-Key": "phase2-job-1"},
    )
    assert response.status_code == 202
    job_id = response.json()["job"]["id"]
    job = _wait_for_job(client, job_id, "COMPLETED")
    assert job["display_id"] == "JOB-000001"
    assert job["plan"]["objective"] == "Plan de prueba"
    assert job["steps"][0]["status"] == "SUCCEEDED"
    replay = client.post(
        "/api/jobs",
        json={"request_text": "Solicitud diferente."},
        headers={"Idempotency-Key": "phase2-job-1"},
    )
    assert replay.status_code == 200
    assert replay.json()["job"]["id"] == job_id
    assert len(client.get("/api/jobs").json()) == 1
    with app.state.engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM jobs").scalar_one() == 1
        assert (
            connection.exec_driver_sql("SELECT COUNT(*) FROM events WHERE job_id = ?", (job_id,)).scalar_one()
            == 6
        )


def test_cancel_active_plan_kills_fake_process(client: TestClient, app, monkeypatch) -> None:
    monkeypatch.setenv("FAKE_PLAN_DELAY", "1")
    response = client.post(
        "/api/jobs",
        json={"request_text": "Wait so cancellation can be tested."},
        headers={"Idempotency-Key": "phase2-cancel"},
    )
    assert response.status_code == 202
    job_id = response.json()["job"]["id"]
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        current = client.get(f"/api/jobs/{job_id}").json()
        if current["status"] == "PLANNING" and app.state.supervisor._runs:
            break
        time.sleep(0.02)
    cancelled = client.post(
        f"/api/jobs/{job_id}/cancel",
        json={},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "CANCELLED"
    repeated = client.post(f"/api/jobs/{job_id}/cancel", json={})
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "CANCELLED"
    assert not app.state.supervisor._runs


def test_job_sse_replays_after_last_event_id(client: TestClient, app) -> None:
    response = client.post(
        "/api/jobs",
        json={"request_text": "Create a plan and replay its events."},
        headers={"Idempotency-Key": "phase2-sse"},
    )
    job_id = response.json()["job"]["id"]
    _wait_for_job(client, job_id, "COMPLETED")
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": f"/api/jobs/{job_id}/events",
        "raw_path": f"/api/jobs/{job_id}/events".encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"last-event-id", b"1")],
        "client": ("test", 1),
        "server": ("test", 80),
        "app": app,
    }

    async def receive_replay():
        response = await job_events(job_id, Request(scope))
        received = []
        try:
            async for chunk in response.body_iterator:
                for line in str(chunk).splitlines():
                    if line.startswith("data: "):
                        received.append(json.loads(line[6:]))
                if (
                    received
                    and received[-1]["type"] == "job.state_changed"
                    and received[-1]["data"].get("to") == "COMPLETED"
                ):
                    return received
        finally:
            await response.body_iterator.aclose()
        return received

    received = asyncio.run(receive_replay())
    sequences = [event["seq"] for event in received]
    assert sequences == sorted(set(sequences))
    assert sequences[0] == 2
    assert any(event["type"] == "job.plan" for event in received)
    assert received[-1]["data"]["to"] == "COMPLETED"


def test_job_endpoints_validate_contracts(client: TestClient) -> None:
    assert client.post("/api/jobs", json={"request_text": "test"}).status_code == 400
    assert (
        client.post("/api/jobs", json={"request_text": " "}, headers={"Idempotency-Key": "bad"}).status_code
        == 422
    )
    assert client.get("/api/jobs/missing").status_code == 404
    assert client.get("/api/jobs/missing/events", headers={"Last-Event-ID": "-1"}).status_code == 400
