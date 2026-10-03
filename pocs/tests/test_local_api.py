from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from poc04_mcp_tools.local_api import create_app


def test_local_api_auth_and_redacted_log(tmp_path: Path) -> None:
    token = "a" * 64
    log = tmp_path / "api.ndjson"
    client = TestClient(create_app(token, log))
    url = "/internal/mcp/get_job_status"
    assert client.post(url, json={"job_id": "JOB-000001"}).status_code == 401
    assert client.post(url, json={"job_id": "JOB-000001"},
                       headers={"Authorization": "Bearer wrong"}).status_code == 401
    response = client.post(url, json={"job_id": "JOB-000001"},
                           headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == {"job_id": "JOB-000001", "status": "IMPLEMENTING", "iteration": 1}
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert [row["status"] for row in rows] == [401, 401, 200]
    assert [row["auth_ok"] for row in rows] == [False, False, True]
    assert token not in log.read_text(encoding="utf-8")
