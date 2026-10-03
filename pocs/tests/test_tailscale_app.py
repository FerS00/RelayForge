from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from poc11_tailscale.app import create_app


def test_whoami_reflects_only_selected_identity_headers_and_logs(tmp_path: Path) -> None:
    log = tmp_path / 'requests.ndjson'
    client = TestClient(create_app(log, sse_minutes=0))
    response = client.get('/whoami', headers={
        'Tailscale-User-Login': 'owner@example.com', 'Tailscale-User-Name': 'Owner',
        'Tailscale-User-Profile-Pic': 'https://profile.invalid/image', 'Origin': 'https://tailnet.invalid',
        'X-Forwarded-For': '100.64.0.1', 'X-Forwarded-Proto': 'https', 'Cookie': 'private-cookie',
        'Authorization': 'Bearer private-token',
    })
    assert response.status_code == 200
    assert response.json()['Tailscale-User-Login'] == 'owner@example.com'
    assert response.json()['Tailscale-User-Profile-Pic'] is True
    assert 'Cookie' not in response.json() and 'Authorization' not in response.json()
    raw = log.read_text(encoding='utf-8')
    row = json.loads(raw)
    assert row['path'] == '/whoami' and row['Tailscale-User-Name'] == 'Owner'
    assert 'private-cookie' not in raw and 'private-token' not in raw
    assert 'owner@example.com' not in raw


def test_index_is_self_contained_and_opens_sse(tmp_path: Path) -> None:
    response = TestClient(create_app(tmp_path / 'app.ndjson')).get('/')
    assert response.status_code == 200
    assert 'EventSource' in response.text and "fetch('/whoami')" in response.text
    assert 'http://' not in response.text and 'https://' not in response.text


def test_sse_emits_tick_ids_and_continues_from_last_event_id(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path / 'app.ndjson', sse_minutes=0.0005))
    first = client.get('/sse')
    assert first.headers['content-type'].startswith('text/event-stream')
    assert 'id: 1\nevent: tick\ndata: {"n": 1,' in first.text
    continued = client.get('/sse', headers={'Last-Event-ID': '41'})
    assert 'id: 42\nevent: tick\ndata: {"n": 42,' in continued.text
