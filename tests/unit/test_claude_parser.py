from __future__ import annotations

import json
from pathlib import Path

from relayforge.adapters.base import ParseState
from relayforge.adapters.claude.parser import parse_line

ROOT = Path(__file__).resolve().parents[2]


def records(name: str):
    return [
        json.loads(line)
        for line in (ROOT / "tests/fixtures/claude/2.1.283" / name).read_text(encoding="utf-8").splitlines()
    ]


def test_synthetic_fixture_emits_text_and_result() -> None:
    state = ParseState()
    emitted = [
        event for row in records("text_turn.ndjson") for event in parse_line(json.dumps(row).encode(), state)
    ]
    assert any(event.type == "agent.message" for event in emitted)
    assert any(event.type == "agent.result" for event in emitted)
    assert not any("thinking" in str(event.data).lower() for event in emitted)


def test_synthetic_resume_fixture_contains_text_and_delta() -> None:
    emitted = [
        event
        for row in records("resume_turn.ndjson")
        for event in parse_line(json.dumps(row).encode(), ParseState())
    ]
    assert any(event.type == "agent.message" for event in emitted)
    assert any(event.type == "agent.message.delta" for event in emitted)


def test_parser_discards_malformed_unknown_and_non_text_blocks() -> None:
    state = ParseState()
    for line in (
        b"",
        b"not-json",
        b"[]",
        b'{"unknown": 1}',
        b'{"type":"future"}',
        b'{"type":"rate_limit_event"}',
        b'{"type":"system/init"}',
    ):
        assert parse_line(line, state) == []
    mixed = {
        "type": "assistant",
        "message": {
            "content": [
                {"type": "text", "text": "kept"},
                {"type": "thinking", "thinking": "hidden"},
                {"type": "tool_use", "input": {"x": "hidden"}},
                {"type": "future", "text": "hidden"},
            ]
        },
    }
    assert parse_line(json.dumps(mixed).encode(), state)[0].data["text"] == "kept"
    result = parse_line(b'{"type":"result","is_error":true,"result":"synthetic"}', state)
    assert result[0].data["is_error"] is True
    assert state.unparsed_lines == 5
