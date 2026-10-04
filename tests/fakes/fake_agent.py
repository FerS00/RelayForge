from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def write(record: dict[str, object], *, split: bool = False) -> None:
    line = json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n"
    mark = time.time()
    sys.stdout.buffer.write(line[:1] if split else line)
    sys.stdout.buffer.flush()
    if split:
        time.sleep(0.05)
        sys.stdout.buffer.write(line[1:])
        sys.stdout.buffer.flush()
    log_line(record, mark)


def log_line(record: dict[str, object], mark: float) -> None:
    log_path = os.getenv("FAKE_AGENT_LOG")
    if log_path:
        path = Path(log_path)
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"lines": []}
        data["lines"].append({"record": record, "written_at": mark})
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def stream(text: str, delay: float = 0.0) -> None:
    write({"type": "stream_event", "event": {"type": "message_start"}, "parent_tool_use_id": None})
    for piece in (text[:2], text[2:5], text[5:]):
        if piece:
            write(
                {
                    "type": "stream_event",
                    "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": piece}},
                    "parent_tool_use_id": None,
                }
            )
            if delay:
                time.sleep(delay)
    write({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})
    write({"type": "stream_event", "event": {"type": "message_stop"}, "parent_tool_use_id": None})


def main() -> int:
    prompt = sys.stdin.read()
    log_path = os.getenv("FAKE_AGENT_LOG")
    if log_path:
        Path(log_path).write_text(
            json.dumps({"argv": sys.argv[1:], "prompt": prompt, "lines": []}, ensure_ascii=False),
            encoding="utf-8",
        )
    scenario = os.getenv("FAKE_AGENT_SCENARIO", "ok")
    if scenario == "blocks":
        sys.stderr.write("FAKE_STDERR_MARKER\n")
        write({"type": "system", "subtype": "init", "skills": ["FAKE_SKILL_MARKER"]})
        write(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": "FAKE_THINKING_MARKER"},
                        {"type": "tool_use", "input": {"marker": "FAKE_TOOL_MARKER"}},
                        {"type": "text", "text": "visible answer"},
                        {"type": "other", "text": "FAKE_OTHER_MARKER"},
                    ]
                },
            }
        )
    elif scenario == "error_result":
        write({"type": "result", "is_error": True, "result": "synthetic failure"})
    elif scenario == "no_result":
        write({"type": "assistant", "message": {"content": [{"type": "text", "text": "answer"}]}})
    elif scenario == "exit_nonzero":
        write({"type": "result", "is_error": False})
        return 7
    elif scenario == "partial_lines":
        record = {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "Café 🙂 split"},
            },
            "parent_tool_use_id": None,
        }
        encoded = json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\n"
        mark = time.time()
        emoji = encoded.index("🙂".encode())
        sys.stdout.buffer.write(encoded[: emoji + 2])
        sys.stdout.buffer.flush()
        time.sleep(0.05)
        sys.stdout.buffer.write(encoded[emoji + 2 :])
        sys.stdout.buffer.flush()
        log_line(record, mark)
    elif scenario == "oversized_line":
        sys.stdout.buffer.write(b"x" * (8 * 1024 * 1024 + 1) + b"\n")
        sys.stdout.buffer.flush()
    elif scenario == "spawn_children":
        grandchild = "import time; time.sleep(120)"
        child = (
            "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',sys.argv[1]]); time.sleep(120)"
        )
        subprocess.Popen([sys.executable, "-c", child, grandchild])
        time.sleep(30)
    elif scenario == "two_messages":
        stream("first response", delay=0.25)
        time.sleep(1.1)
        stream("second response", delay=0.25)
    else:
        stream("fake answer")
    if scenario not in {"error_result", "no_result", "spawn_children"}:
        write({"type": "result", "is_error": False, "duration_ms": 2})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
