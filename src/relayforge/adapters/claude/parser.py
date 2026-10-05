from __future__ import annotations

import json
from typing import Any

from relayforge.adapters.base import NormalizedEvent, ParseState


def parse_line(line: bytes, state: ParseState) -> list[NormalizedEvent]:
    try:
        record = json.loads(line.decode("utf-8", errors="replace"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        state.unparsed_lines += 1
        return []
    if not isinstance(record, dict) or not isinstance(record.get("type"), str):
        state.unparsed_lines += 1
        return []
    kind = record["type"]
    if kind == "assistant":
        message = record.get("message", {})
        blocks = message.get("content", []) if isinstance(message, dict) else []
        text = (
            "".join(
                str(block.get("text", ""))
                for block in blocks
                if isinstance(block, dict) and block.get("type") == "text"
            )
            if isinstance(blocks, list)
            else ""
        )
        return [NormalizedEvent("agent.message", "claude", None, {"text": text})] if text else []
    if kind == "stream_event":
        event = record.get("event")
        if not isinstance(event, dict) or event.get("type") != "content_block_delta":
            return []
        delta = event.get("delta")
        if (
            not isinstance(delta, dict)
            or delta.get("type") != "text_delta"
            or record.get("parent_tool_use_id") is not None
        ):
            return []
        delta_text = delta.get("text")
        if not isinstance(delta_text, str):
            return []
        return [NormalizedEvent("agent.message.delta", "claude", None, {"text": delta_text})]
    if kind == "result":
        is_error = bool(record.get("is_error", False))
        state.result_seen = True
        state.result_is_error = is_error
        data: dict[str, Any] = {"is_error": is_error}
        structured_output = record.get("structured_output")
        if isinstance(structured_output, dict):
            state.structured_output = structured_output
            data["structured_output"] = structured_output
        if is_error:
            detail_value = record.get("result")
            if isinstance(detail_value, str):
                data["detail"] = detail_value[:300]
                state.failure_detail = detail_value[:2000]
        usage = record.get("usage")
        if isinstance(usage, dict):
            state.usage = {
                key: usage[key]
                for key in ("input_tokens", "output_tokens")
                if isinstance(usage.get(key), int) and usage[key] >= 0
            }
        duration = record.get("duration_ms")
        if isinstance(duration, int):
            data["duration_ms"] = duration
        return [NormalizedEvent("agent.result", "claude", None, data)]
    if kind.startswith("system/") or kind in {"system", "rate_limit_event"}:
        return []
    state.unparsed_lines += 1
    return []
