from pathlib import Path

from relayforge.adapters.base import RunSpec
from relayforge.adapters.claude.adapter import ClaudeAdapter
from relayforge.adapters.codex.adapter import CodexAdapter, CodexRunSpec


def test_models_are_per_invocation_and_planning_is_read_only(tmp_path: Path):
    codex = CodexAdapter("codex.exe")
    plan = codex.build_run(
        CodexRunSpec(tmp_path, "plan", tmp_path / "schema", model="planner-model", sandbox="read-only")
    )
    implementation = codex.build_run(
        CodexRunSpec(tmp_path, "implement", tmp_path / "schema", model="coder-model")
    )
    assert plan.argv[plan.argv.index("--model") + 1] == "planner-model"
    assert plan.argv[plan.argv.index("-s") + 1] == "read-only"
    assert implementation.argv[implementation.argv.index("--model") + 1] == "coder-model"
    assert implementation.argv[implementation.argv.index("-s") + 1] == "workspace-write"
    resumed = codex.build_run(CodexRunSpec(tmp_path, "resume", tmp_path / "schema", "thread-1", "next-model"))
    assert "-s" not in resumed.argv
    assert "sandbox_mode='workspace-write'" in resumed.argv
    claude = ClaudeAdapter("claude.exe", "default-model")
    selected = claude.build_run(RunSpec("session", False, tmp_path, "plan", model="selected-model"))
    default = claude.build_run(RunSpec("session", False, tmp_path, "plan"))
    assert selected.argv[selected.argv.index("--model") + 1] == "selected-model"
    assert default.argv[default.argv.index("--model") + 1] == "default-model"
    assert "Bash" in selected.argv and "Write" in selected.argv
