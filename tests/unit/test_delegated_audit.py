import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from relayforge.adapters.antigravity import delegated
from relayforge.adapters.antigravity.adapter import AntigravityAdapter


def prepare(tmp_path, monkeypatch, gate_decision="allow", exit_code=0, report_verdict="APPROVED"):
    run = tmp_path / "run"
    run.mkdir()
    runner = tmp_path / "runner.py"
    runner.write_text("# trusted fixture", encoding="utf-8")
    checked = []

    def execute(argv, **kwargs):
        command_path = Path(argv[argv.index("--commands-json") + 1])
        commands = json.loads(command_path.read_text(encoding="utf-8"))
        checked.extend(commands)
        assert "--dispatch" in commands[0] and "git-check" in commands[0]
        assert kwargs["timeout"] == 75
        evidence = {
            "transport_status": "Completado",
            "cli_status": "SUCCESS",
            "audit_status": "APROBADO",
            "changed_sources": [],
            "denied_actions": [],
            "missing_commands": [],
            "timeout": False,
        }
        (run / "result.json").write_text(json.dumps(evidence), encoding="utf-8")
        (run / "gate.ndjson").write_text(json.dumps({"decision": gate_decision}) + "\n", encoding="utf-8")
        (run / "check-0.json").write_text(
            json.dumps({"command": commands[0], "exit_code": exit_code}), encoding="utf-8"
        )
        value = {"verdict": report_verdict, "summary": "Reviewed", "findings": []}
        (run / "report.md").write_text(
            "ESTADO: APROBADO\nRELAYFORGE_JSON_BEGIN\n" + json.dumps(value) + "\nRELAYFORGE_JSON_END",
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout=json.dumps({"run": str(run)}).encode())

    monkeypatch.setattr(delegated.subprocess, "run", execute)
    return runner, checked


def test_delegated_runner_keeps_scoped_dispatcher_and_validates_output(tmp_path, monkeypatch):
    runner, checked = prepare(tmp_path, monkeypatch)
    result = AntigravityAdapter(runner=runner, timeout_seconds=30)._audit(
        tmp_path,
        [],
        [{"name": "git-check", "argv": ["git", "diff", "--check"], "timeout_seconds": 5}],
        1,
        "diff",
    )
    assert result.verdict == "APPROVED" and checked


@pytest.mark.parametrize(
    "gate, exit_code, verdict", [("deny", 0, "APPROVED"), ("allow", 1, "APPROVED"), ("allow", 0, "REJECTED")]
)
def test_delegated_runner_does_not_accept_bad_evidence(tmp_path, monkeypatch, gate, exit_code, verdict):
    runner, _ = prepare(tmp_path, monkeypatch, gate, exit_code, verdict)
    result = AntigravityAdapter(runner=runner, timeout_seconds=30)._audit(
        tmp_path,
        [],
        [{"name": "git-check", "argv": ["git", "diff", "--check"], "timeout_seconds": 5}],
        1,
        "diff",
    )
    assert result.verdict == "BLOCKED"
