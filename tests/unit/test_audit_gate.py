import hashlib
import io
import json
from pathlib import Path

from relayforge.adapters.antigravity import gate
from relayforge.adapters.antigravity.gate import decide


def test_gate_denies_unknown_tool_and_outside_path(tmp_path: Path) -> None:
    worktree = tmp_path / "repo"
    worktree.mkdir()
    allowed = worktree / "src.py"
    allowed.write_text("pass", encoding="utf-8")
    policy = {"worktree": str(worktree), "files": [str(allowed)], "commands": {}}
    assert decide(policy, {"toolCall": {"name": "edit_file", "args": {}}})[0] == "deny"
    assert (
        decide(
            policy, {"toolCall": {"name": "view_file", "args": {"AbsolutePath": str(tmp_path / "secret")}}}
        )[0]
        == "deny"
    )
    assert (
        decide(policy, {"toolCall": {"name": "view_file", "args": {"AbsolutePath": str(allowed)}}})[0]
        == "allow"
    )


def test_gate_allows_only_exact_declared_check(tmp_path: Path) -> None:
    worktree = tmp_path / "repo"
    worktree.mkdir()
    policy = {
        "worktree": str(worktree),
        "files": [],
        "commands": {"pytest": {"name": "pytest", "argv": ["pytest", "-q"]}},
        "dispatch_commands": {"pytest -q": "pytest"},
    }
    call = {"toolCall": {"name": "run_command", "args": {"CommandLine": "pytest -q", "Cwd": str(worktree)}}}
    assert decide(policy, call) == ("allow", "command and working directory are allowlisted")
    call["toolCall"]["args"]["CommandLine"] = "pytest -q; whoami"
    assert decide(policy, call)[0] == "deny"


def test_gate_denied_write_is_logged_without_changing_file(tmp_path: Path, monkeypatch, capsys) -> None:
    worktree = tmp_path / "repo"
    worktree.mkdir()
    target = worktree / "source.py"
    target.write_text("safe", encoding="utf-8")
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(
        json.dumps({"worktree": str(worktree), "files": [], "commands": {}}), encoding="utf-8"
    )
    call = {"toolCall": {"name": "edit_file", "args": {"path": str(target), "content": "bad"}}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(call)))
    assert gate.main(["--policy", str(policy_path)]) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "deny"
    assert json.loads((tmp_path / "gate.ndjson").read_text(encoding="utf-8"))["decision"] == "deny"
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before
