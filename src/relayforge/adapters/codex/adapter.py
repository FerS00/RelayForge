from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from relayforge.adapters.base import LaunchPlan, NormalizedEvent, ParseState, RunOutcome


@dataclass(frozen=True)
class CodexRunSpec:
    cwd: Path
    prompt: str
    schema_path: Path
    resume_thread_id: str | None = None
    model: str = ""
    sandbox: str = "workspace-write"


@dataclass(frozen=True)
class CodexAdapter:
    executable: str = "codex"
    name: str = "codex"

    def build_run(self, spec: CodexRunSpec) -> LaunchPlan:
        if spec.resume_thread_id:
            thread_id = spec.resume_thread_id
            if not thread_id or any(
                char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
                for char in thread_id
            ):
                raise ValueError("El thread_id de Codex no es válido.")
            argv = [self.executable, "exec", "resume", thread_id, "--json", "-C", str(spec.cwd)]
        else:
            argv = [self.executable, "exec", "--json", "-C", str(spec.cwd)]
        if spec.sandbox not in {"read-only", "workspace-write"}:
            raise ValueError("Sandbox no permitido.")
        if spec.model:
            argv.extend(["--model", spec.model])
        argv.extend(
            ["-c", f"sandbox_mode='{spec.sandbox}'"] if spec.resume_thread_id else ["-s", spec.sandbox]
        )
        argv.extend(
            [
                "-c",
                "windows.sandbox='unelevated'",
                "--output-schema",
                str(spec.schema_path),
                "-",
            ]
        )
        return LaunchPlan(tuple(argv), Path(spec.cwd), spec.prompt)

    @staticmethod
    def parse_line(line: bytes, state: ParseState) -> list[NormalizedEvent]:
        try:
            raw = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            state.unparsed_lines += 1
            return []
        if not isinstance(raw, dict) or not isinstance(raw.get("type"), str):
            state.unparsed_lines += 1
            return []
        event_type = raw["type"]
        item_value = raw.get("item")
        item: dict[str, Any] = item_value if isinstance(item_value, dict) else {}
        if event_type == "thread.started":
            thread_id = raw.get("thread_id")
            return [NormalizedEvent("agent.thread", "codex", None, {"thread_id": thread_id})]
        if event_type == "item.completed" and item.get("type") == "file_change":
            changes = item.get("changes", [])
            if not isinstance(changes, list):
                return []
            result: list[NormalizedEvent] = []
            for change in changes:
                if isinstance(change, dict) and isinstance(change.get("path"), str):
                    result.append(
                        NormalizedEvent(
                            "file.changed",
                            "codex",
                            None,
                            {"path": change["path"], "kind": str(change.get("kind", "unknown"))},
                        )
                    )
            return result
        if event_type == "item.completed" and item.get("type") == "agent_message":
            text = item.get("text")
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = None
                state.structured_output = parsed
                return [NormalizedEvent("agent.message", "codex", None, {"text": text})]
        if event_type == "turn.completed":
            state.result_seen = True
            usage = raw.get("usage")
            if isinstance(usage, dict):
                state.usage = {
                    key: usage[key]
                    for key in ("input_tokens", "output_tokens")
                    if isinstance(usage.get(key), int) and usage[key] >= 0
                }
            return [NormalizedEvent("agent.turn_completed", "codex", None, {})]
        if event_type == "turn.failed":
            state.result_seen = True
            state.result_is_error = True
            error = raw.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                state.failure_detail = str(error["message"])[:2000]
            return [NormalizedEvent("agent.turn_failed", "codex", None, {})]
        if event_type == "error" and isinstance(raw.get("message"), str):
            state.failure_detail = str(raw["message"])[:2000]
        return []

    @staticmethod
    def classify_exit(code: int, state: ParseState) -> RunOutcome:
        if code != 0 or state.result_is_error:
            return "failed"
        if not state.result_seen:
            return "invalid_output"
        output = state.structured_output
        if not isinstance(output, dict) or output.get("completed") is not True:
            return "invalid_output"
        return "ok"
