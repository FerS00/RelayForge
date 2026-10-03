from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from poc10_autostart.probe import (
    agy_result,
    claude_auth_result,
    claude_result,
    codex_auth_result,
    codex_result,
    main,
    write_evidence,
)


def test_claude_auth_uses_logged_in_and_drops_account_fields() -> None:
    output = '{\n  "loggedIn": true,\n  "email": "private@example.com",' \
        '\n  "orgId": "private-org",\n  "orgName": "Private Org"\n}\n'
    assert claude_auth_result(0, output) == ("AVAILABLE", {"loggedIn": True})
    assert claude_auth_result(1, '{"loggedIn":false}') == ("AUTH_REQUIRED", {"loggedIn": False})


def test_codex_auth_status_text_is_conservative() -> None:
    assert codex_auth_result(0, "Logged in using ChatGPT\n") == ("AVAILABLE", "Logged in using ChatGPT")
    assert codex_auth_result(1, "Not logged in\n") == ("AUTH_REQUIRED", "Not logged in")
    assert codex_auth_result(0, "Unexpected\n")[0] == "UNKNOWN"


def test_deep_probe_extracts_terminal_agent_events() -> None:
    claude = '{"type":"assistant","message":{}}\n{"type":"result","is_error":false,' \
        '"result":"OK"}\n'
    codex = '{"type":"item.completed","item":{"type":"agent_message","text":"OK"}}\n' \
        '{"type":"turn.completed"}\n'
    agy = '{"event":"progress"}\n{"event":"result","result":{"status":"SUCCESS",' \
        '"response":"OK"}}\n'
    assert claude_result(claude) == {"event": "result", "is_error": False, "result_nonempty": True}
    assert codex_result(codex) == {"event": "turn.completed", "result_nonempty": True}
    assert agy_result(agy) == {"event": "result", "status": "SUCCESS", "result_nonempty": True}


def test_result_parsers_do_not_treat_intermediate_events_as_final() -> None:
    assert claude_result('{"type":"assistant","result":"not final"}\n')["event"] is None
    assert codex_result('{"type":"item.completed","item":{"type":"agent_message",' \
                        '"text":"not final"}}\n')["event"] is None
    assert agy_result('{"event":"progress","result":{"status":"SUCCESS","response":"OK"}}')[
        "event"] is None


def test_write_evidence_never_overwrites_same_mode_and_process(tmp_path: Path) -> None:
    now = datetime(2026, 10, 3, 2, 40, 0)

    first = write_evidence(tmp_path, "StartupS4U", '{"run":1}', now=now, pid=1234)
    second = write_evidence(tmp_path, "StartupS4U", '{"run":2}', now=now, pid=1234)

    assert first.name == "20261003-024000-StartupS4U-1234.json"
    assert second.name == "20261003-024000-StartupS4U-1234-2.json"
    assert first.read_text(encoding="utf-8") == '{"run":1}\n'
    assert second.read_text(encoding="utf-8") == '{"run":2}\n'


def test_probe_evidence_includes_run_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "poc10_autostart.probe.run_probe",
        lambda out_dir, deep, git_remote: {"agents": {"claude": {"auth": "AVAILABLE"}}},
    )

    assert main(["--out-dir", str(tmp_path), "--label", "Logon"]) == 0

    evidence_path = next(tmp_path.glob("*-Logon-*.json"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["label"] == "Logon"
    assert evidence["pid"] > 0
    assert evidence["started_at"]
    assert evidence["boot_time"]


def test_probe_rejects_invalid_label(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--dry-run", "--label", "bad label"])

    assert error.value.code == 2
    assert "label debe tener" in capsys.readouterr().err
