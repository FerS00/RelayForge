from __future__ import annotations

import json
from pathlib import Path

import poc07_backend_restart.supervisor as supervisor
from poc07_backend_restart.supervisor import (
    is_final,
    is_not_resumable,
    read_new_lines,
    starts_conversation,
)


def test_read_new_lines_keeps_partial_bytes_and_offsets(tmp_path: Path) -> None:
    path = tmp_path / "stream.ndjson"
    path.write_bytes(b'{"type":"one"}\n{"type":"two"')
    lines, offset = read_new_lines(path, 0)
    assert lines == [b'{"type":"one"}']
    assert offset == len(b'{"type":"one"}\n')
    with path.open("ab") as stream:
        stream.write(b"}\n")
    lines, new_offset = read_new_lines(path, offset)
    assert lines == [b'{"type":"two"}']
    assert new_offset == len(path.read_bytes())
    assert json.loads(lines[0]) == {"type": "two"}


def test_is_final_uses_confirmed_event_contracts() -> None:
    assert is_final("claude", {"type": "result"})
    assert not is_final("claude", {"type": "assistant"})
    assert is_final("codex", {"type": "turn.completed"})
    assert is_final("codex", {"type": "turn.failed"})
    assert not is_final("codex", {"type": "item.completed"})


def test_conversation_start_events_match_agent_contracts() -> None:
    assert starts_conversation("claude", {"type": "assistant"})
    assert not starts_conversation("claude", {"type": "hook_started"})
    assert starts_conversation("codex", {"type": "item.completed"})
    assert not starts_conversation("codex", {"type": "turn.completed"})


def test_no_conversation_result_is_not_resumable_only_for_claude() -> None:
    event = {"type": "result", "subtype": "error_during_execution",
             "errors": ["No conversation found with session ID: session"]}
    assert is_not_resumable("claude", event)
    assert not is_not_resumable("claude", {**event, "errors": ["another error"]})
    assert not is_not_resumable("codex", event)


def test_consume_preserves_not_resumable_status_after_process_exit(
    tmp_path: Path, monkeypatch,
) -> None:
    output = tmp_path / "agent-2.ndjson"
    output.write_text(json.dumps({"type": "result", "subtype": "error_during_execution",
                                  "errors": ["No conversation found with session ID: session"]}) + "\n",
                      encoding="utf-8")
    state_path = tmp_path / "state.json"
    state = {"agent": "claude", "stdout": str(output), "offset": 0, "lines": 0,
             "pid": 123, "create_time": 1.0, "status": "running"}
    monkeypatch.setattr(supervisor, "_alive", lambda _: False)

    result = supervisor._consume(state_path, state, wait_for_process=False)

    assert result["status"] == "not_resumable"
