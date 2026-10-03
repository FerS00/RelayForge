from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.conftest import make_sandbox
from poc08_approval.run import _has_permission_denial

POCS = Path(__file__).resolve().parents[1]
FORBIDDEN = {"--dangerously-skip-permissions", "--dangerously-bypass-approvals-and-sandbox",
             "--dangerously-bypass-hook-trust", "danger-full-access", "--last", "--sandbox"}


def run_script(script: str, *args: str) -> list:
    result = subprocess.run([sys.executable, str(POCS / script), *args], cwd=POCS,
                            capture_output=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    return json.loads(result.stdout.decode("utf-8", errors="replace"))


def test_agent_runners_dry_run(tmp_path: Path) -> None:
    one = run_script("poc01_claude_stream/run.py", "--repo", "x", "--dry-run")
    two = run_script("poc02_codex_events/run.py", "--repo", "x", "--dry-run")
    for codex_argv in two:
        assert "--effort" not in codex_argv
        assert any(codex_argv[index] == "-c" and
                   codex_argv[index + 1].startswith('model_reasoning_effort="')
                   for index in range(len(codex_argv) - 1))
    repo = make_sandbox(tmp_path / "sandbox")
    three = run_script("poc03_antigravity_audit/run.py", "--worktree", str(repo), "--case", "normal", "--dry-run")
    rendered = json.dumps([one, two, three])
    for forbidden in FORBIDDEN:
        assert forbidden not in rendered
    assert "AZUL-7" not in rendered
    assert "Implementa tú directamente" not in rendered
    assert "corrige tú mismo" not in rendered
    hooks_path = Path(three["hooks_path"])
    hooks_file = json.loads(hooks_path.read_text(encoding="utf-8"))
    hooks = hooks_file["relayforge-poc03"]["PreToolUse"]
    assert len(hooks) == 1
    hook = hooks[0]
    assert hook["matcher"] == "*"
    assert hook["hooks"][0]["type"] == "command"
    assert hook["hooks"][0]["command"].startswith(sys.executable)
    assert hook["hooks"][0]["timeout"] == 10
    assert three["policy"]["commands"] == []
    check_path = str(Path(three["policy"]["run_dir"]) / "check-0.json")
    assert check_path in three["policy"]["files"]
    assert not Path(check_path).exists()


def test_phase_0b_runners_dry_run(tmp_path: Path) -> None:
    four = run_script("poc04_mcp_tools/run.py", "--repo", "x", "--dry-run")
    seven = run_script("poc07_backend_restart/run.py", "--repo", "x", "--dry-run")
    eight = run_script("poc08_approval/run.py", "--repo", "x", "--dry-run")
    nine = run_script("poc09_health/run.py", "--dry-run", "--deep")
    rendered = json.dumps([four, seven, eight, nine], ensure_ascii=False)
    for forbidden in FORBIDDEN:
        assert forbidden not in rendered
    for prompt_marker in ("RF-ECHO-OK", "VERDE-42", "RF-APPROVED-RUN", "RF-DENIED-RUN",
                          "Usa get_job_status", "Delega en Codex", "Estás dentro de RelayForge"):
        assert prompt_marker not in rendered
    assert "--verbose" in rendered
    assert "--permission-mode" in rendered and '"default"' in rendered
    assert "mcp__rfperm__approval_prompt" in rendered
    assert len(eight) == 3
    assert "--print-timeout" in nine["deep_probe"]


def test_approval_denial_detector_uses_denial_events_or_tool_results() -> None:
    assert _has_permission_denial([{"type": "result", "permission_denials": [{"tool_name": "Write"}]}])
    assert _has_permission_denial([{"type": "user", "message": {"content": [
        {"type": "tool_result", "content": "Permission to use Write has been denied."}
    ]}}])
    assert not _has_permission_denial([{"type": "tool_result", "content": "OK"}])


def test_phase_0c_probe_dry_run() -> None:
    ten = run_script("poc10_autostart/probe.py", "--dry-run", "--deep", "--label", "Logon",
                     "--git-remote-check", "https://example.invalid/repo.git")
    rendered = json.dumps(ten, ensure_ascii=False)
    for command in ten.values():
        assert command
    assert '"claude"' in rendered and '"codex"' in rendered and '"agy"' in rendered
    assert ten["label"] == "Logon"
    assert '"git", "ls-remote", "--heads"' in rendered
    assert "--verbose" in rendered and "--print-timeout" in rendered
