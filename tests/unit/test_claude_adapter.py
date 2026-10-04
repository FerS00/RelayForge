from pathlib import Path

from relayforge.adapters.base import RunSpec
from relayforge.adapters.claude.adapter import ClaudeAdapter


def test_launch_arguments_and_session_modes() -> None:
    adapter = ClaudeAdapter("claude", "sonnet")
    fresh = adapter.build_run(RunSpec("00000000-0000-4000-8000-000000000000", False, Path.cwd(), "prompt"))
    resumed = adapter.build_run(RunSpec("00000000-0000-4000-8000-000000000000", True, Path.cwd(), "next"))
    assert "--session-id" in fresh.argv and "--resume" not in fresh.argv
    assert "--resume" in resumed.argv and "--session-id" not in resumed.argv
    assert fresh.argv.count("--permission-mode") == 1 and "default" in fresh.argv
    assert "--include-partial-messages" in fresh.argv
    assert "Bash(codex:*)" in fresh.argv and "Bash(codex *)" in fresh.argv
    assert not any(arg.startswith("--dangerously") for arg in fresh.argv)
    assert fresh.stdin_text == "prompt"
