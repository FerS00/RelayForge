from __future__ import annotations

import json
import sys
from pathlib import Path

from poc03_antigravity_audit.gate import decide, main


def test_gate_allow_deny_matrix(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    allowed = workspace / "source.py"
    allowed.write_text("pass", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    policy = {"files": [str(allowed)], "workspace": str(workspace), "run_dir": str(run_dir),
              "commands": ["python -m pytest -q"], "reviewed_commands": [{"argv": ["python", "-m", "pytest"]}]}
    allow, _ = decide(policy, {"toolCall": {"name": "view_file", "args": {"AbsolutePath": str(allowed)}}})
    assert allow == "allow"
    assert decide(policy, {"toolCall": {"name": "view_file", "args": {
        "AbsolutePath": str(workspace / "other")}}})[0] == "deny"
    assert decide(policy, {"toolCall": {"name": "view_file", "args": {
        "AbsolutePath": str(workspace / ".." / "other")}}})[0] == "deny"
    check = run_dir / "check-0.json"
    assert decide(policy, {"toolCall": {"name": "view_file", "args": {"AbsolutePath": str(check)}}})[0] == "allow"
    assert decide(policy, {"toolCall": {"name": "view_file", "args": {
        "AbsolutePath": str(run_dir / "check-1.json")}}})[0] == "deny"
    call = {"toolCall": {"name": "run_command", "args": {"CommandLine": "python -m pytest -q",
            "Cwd": str(workspace), "RunPersistent": False}}}
    assert decide(policy, call)[0] == "allow"
    spaced = {"toolCall": {"name": "run_command", "args": {
        **call["toolCall"]["args"], "CommandLine": "python  -m pytest -q"}}}
    assert decide(policy, spaced)[0] == "deny"
    other_cwd = {"toolCall": {"name": "run_command", "args": {
        **call["toolCall"]["args"], "Cwd": str(tmp_path)}}}
    assert decide(policy, other_cwd)[0] == "deny"
    persistent = {"toolCall": {"name": "run_command", "args": {
        **call["toolCall"]["args"], "RunPersistent": True}}}
    assert decide(policy, persistent)[0] == "deny"
    assert decide(policy, {"toolCall": {"name": "unknown_tool", "args": {}}})[0] == "deny"
    assert decide(policy, {"tool_name": "view_file", "tool_input": {"AbsolutePath": str(allowed)}})[0] == "deny"


def test_invalid_json_fails_closed(tmp_path: Path, monkeypatch, capsys) -> None:
    policy_file = tmp_path / "policy.json"
    policy_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", type("Input", (), {"read": lambda self: "{"})())
    assert main(["--policy", str(policy_file)]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "deny"
