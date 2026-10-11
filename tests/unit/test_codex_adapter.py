from pathlib import Path

from relayforge.adapters.base import ParseState
from relayforge.adapters.codex.adapter import CodexAdapter, CodexRunSpec


def test_codex_build_run_uses_argv_and_can_resume(tmp_path: Path) -> None:
    schema = tmp_path / "schema.json"
    adapter = CodexAdapter("codex.exe")
    initial = adapter.build_run(CodexRunSpec(tmp_path, "do work", schema))
    resumed = adapter.build_run(CodexRunSpec(tmp_path, "continue", schema, "thread-1"))
    assert initial.argv[:4] == ("codex.exe", "exec", "--json", "-C")
    assert "workspace-write" in initial.argv
    assert resumed.argv[3:6] == ("exec", "resume", "thread-1")
    assert initial.argv[-1] == "-"


def test_codex_parser_extracts_thread_changes_and_structured_result() -> None:
    state = ParseState()
    thread = CodexAdapter.parse_line(b'{"type":"thread.started","thread_id":"t-1"}', state)
    change = CodexAdapter.parse_line(
        b'{"type":"item.completed","item":{"type":"file_change","changes":[{"path":"x.py","kind":"add"}]}}',
        state,
    )
    result = CodexAdapter.parse_line(
        b'{"type":"item.completed","item":{"type":"agent_message","text":"{\\"summary\\":\\"done\\",\\"completed\\":true}"}}',
        state,
    )
    CodexAdapter.parse_line(b'{"type":"turn.completed"}', state)
    assert thread[0].data["thread_id"] == "t-1"
    assert change[0].type == "file.changed"
    assert result[0].type == "agent.message"
    assert CodexAdapter.classify_exit(0, state) == "ok"


def test_codex_chat_flags_do_not_require_schema(tmp_path: Path) -> None:
    import pytest

    adapter = CodexAdapter("codex.exe")
    spec = CodexRunSpec(
        tmp_path, "hello", None, model="gpt-6-luna", sandbox="read-only", reasoning_effort="medium"
    )
    argv = adapter.build_run(spec).argv
    assert "--output-schema" not in argv
    assert "read-only" in argv and "gpt-6-luna" in argv
    assert "model_reasoning_effort='medium'" in argv
    with pytest.raises(ValueError, match="Esfuerzo"):
        adapter.build_run(CodexRunSpec(tmp_path, "hello", None, reasoning_effort="ultra"))
