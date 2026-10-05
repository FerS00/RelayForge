from fastapi.testclient import TestClient


def test_doctor_endpoint_reports_check_names_without_command_output(client: TestClient, monkeypatch) -> None:
    import relayforge.api.routes.doctor as doctor_module

    monkeypatch.setattr(
        doctor_module,
        "doctor_report",
        lambda _settings, _engine: {
            "bind": {"status": "PASS"},
            "claude": {"status": "AVAILABLE", "version": "2.1.283", "auth": "AVAILABLE"},
            "agy": {"status": "AVAILABLE", "auth": "UNKNOWN"},
        },
    )
    response = client.get("/api/doctor")
    assert response.status_code == 200
    assert response.json()["claude"]["auth"] == "AVAILABLE"
    assert response.json()["agy"]["auth"] == "UNKNOWN"
    assert "owner@example.test" not in response.text


def test_fingerprint_comparison_rejects_invalid_json(tmp_path, monkeypatch) -> None:
    import json

    import relayforge.doctor.checks as checks

    monkeypatch.setattr(
        checks,
        "_agent",
        lambda name, _auth_args=None: {
            "status": "AVAILABLE",
            "version": f"fake-{name}",
            "auth": "UNKNOWN",
        },
    )

    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert checks.compare_fingerprint(bad) == {
        "status": "ERROR",
        "message": "No se pudo leer un fingerprint JSON válido.",
    }
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"schema": 1}), encoding="utf-8")
    result = checks.compare_fingerprint(good)
    assert result["status"] == "DIFFERENT"
    assert "agents" in result["differences"]


def test_probe_timeout_kills_windows_launcher_children(tmp_path, fake_launcher, monkeypatch):
    import subprocess
    import time

    import psutil
    import pytest

    from relayforge.doctor.checks import _run_cli

    monkeypatch.setenv("FAKE_AGENT_SCENARIO", "spawn_children")
    before = {process.pid for process in psutil.process_iter()}
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        _run_cli([str(fake_launcher), "-p"], timeout=0.6)
    assert time.monotonic() - started < 7
    assert not [
        process
        for process in psutil.process_iter(["pid", "cmdline"])
        if process.pid not in before
        and any("fake_agent.py" in arg for arg in (process.info["cmdline"] or []))
    ]
