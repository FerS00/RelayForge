from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

from relayforge.adapters.base import ConversationContext, NormalizedEvent, ParseState, RunSpec
from relayforge.adapters.claude.adapter import ClaudeAdapter
from relayforge.process.supervisor import RunHandle, Supervisor


@dataclass
class ClaudeOrchestrator:
    adapter: ClaudeAdapter
    supervisor: Supervisor
    output_root: Path
    name: str = "claude"

    async def chat(self, ctx: ConversationContext, message: str) -> AsyncIterator[NormalizedEvent]:
        step_id = ctx.step_id
        spec = RunSpec(ctx.session_id, ctx.session_established, ctx.cwd, message)
        plan = self.adapter.build_run(spec)
        folder = self.output_root / "conversations" / ctx.conversation_id / "steps" / step_id
        folder.mkdir(parents=True, exist_ok=True)
        handle: RunHandle | None = None
        state = ParseState()
        messages: dict[int, str] = {}
        current_message = 0
        pending_text = ""
        pending_since = 0.0
        started = asyncio.get_running_loop().time()
        try:
            handle = await asyncio.to_thread(
                self.supervisor.start,
                plan,
                output_path=folder / "stdout.ndjson",
                stderr_path=folder / "stderr.log",
            )
            while True:
                lines = await asyncio.to_thread(self.supervisor.read_lines, handle)
                for line in lines:
                    try:
                        raw = json.loads(line.decode("utf-8", "replace"))
                    except ValueError:
                        raw = None
                    if isinstance(raw, dict) and raw.get("type") == "stream_event":
                        event = raw.get("event")
                        if isinstance(event, dict) and event.get("type") == "message_start":
                            if pending_text:
                                yield NormalizedEvent(
                                    "agent.message.delta",
                                    "claude",
                                    step_id,
                                    {"text": pending_text, "_message_index": current_message},
                                )
                                pending_text = ""
                            current_message += 1
                            messages[current_message] = ""
                    for parsed in self.adapter.parse_line(line, state):
                        if parsed.type == "agent.message.delta":
                            if not pending_text:
                                pending_since = asyncio.get_running_loop().time()
                            pending_text += parsed.data["text"]
                            messages[current_message] = (
                                messages.get(current_message, "") + parsed.data["text"]
                            )
                            if asyncio.get_running_loop().time() - pending_since >= 0.5:
                                yield NormalizedEvent(
                                    parsed.type,
                                    parsed.actor,
                                    step_id,
                                    {"text": pending_text, "_message_index": current_message},
                                )
                                pending_text = ""
                        elif parsed.type == "agent.message":
                            if pending_text:
                                yield NormalizedEvent(
                                    "agent.message.delta",
                                    "claude",
                                    step_id,
                                    {"text": pending_text, "_message_index": current_message},
                                )
                                pending_text = ""
                            if not messages.get(current_message):
                                current_message += 1
                            messages[current_message] = parsed.data["text"]
                            yield NormalizedEvent(
                                parsed.type,
                                parsed.actor,
                                step_id,
                                {**parsed.data, "_message_index": current_message},
                            )
                        elif parsed.type == "agent.result":
                            yield NormalizedEvent(parsed.type, parsed.actor, step_id, parsed.data)
                code = await asyncio.to_thread(self.supervisor.exit_code, handle)
                if code is not None:
                    for line in await asyncio.to_thread(self.supervisor.read_lines, handle):
                        try:
                            raw = json.loads(line.decode("utf-8", "replace"))
                        except ValueError:
                            raw = None
                        if (
                            isinstance(raw, dict)
                            and raw.get("type") == "stream_event"
                            and isinstance(raw.get("event"), dict)
                            and raw["event"].get("type") == "message_start"
                        ):
                            if pending_text:
                                yield NormalizedEvent(
                                    "agent.message.delta",
                                    "claude",
                                    step_id,
                                    {"text": pending_text, "_message_index": current_message},
                                )
                                pending_text = ""
                            current_message += 1
                            messages[current_message] = ""
                        for parsed in self.adapter.parse_line(line, state):
                            if parsed.type == "agent.message.delta":
                                if not pending_text:
                                    pending_since = asyncio.get_running_loop().time()
                                pending_text += parsed.data["text"]
                                messages[current_message] = (
                                    messages.get(current_message, "") + parsed.data["text"]
                                )
                            elif parsed.type == "agent.message":
                                if pending_text:
                                    yield NormalizedEvent(
                                        "agent.message.delta",
                                        "claude",
                                        step_id,
                                        {"text": pending_text, "_message_index": current_message},
                                    )
                                    pending_text = ""
                                if not messages.get(current_message):
                                    current_message += 1
                                messages[current_message] = parsed.data["text"]
                                yield NormalizedEvent(
                                    parsed.type,
                                    parsed.actor,
                                    step_id,
                                    {**parsed.data, "_message_index": current_message},
                                )
                            else:
                                yield NormalizedEvent(parsed.type, parsed.actor, step_id, parsed.data)
                    if pending_text:
                        yield NormalizedEvent(
                            "agent.message.delta",
                            "claude",
                            step_id,
                            {"text": pending_text, "_message_index": current_message},
                        )
                        pending_text = ""
                    outcome = self.adapter.classify_exit(code, state)
                    detail = "agent_error" if state.result_is_error else ("process_exit" if code else None)
                    yield NormalizedEvent(
                        "agent.exit",
                        "core",
                        step_id,
                        {
                            "outcome": outcome,
                            "detail": detail,
                            "duration_ms": int((asyncio.get_running_loop().time() - started) * 1000),
                            "unparsed_lines": state.unparsed_lines,
                        },
                    )
                    return
                if pending_text and asyncio.get_running_loop().time() - pending_since >= 0.5:
                    yield NormalizedEvent(
                        "agent.message.delta",
                        "claude",
                        step_id,
                        {"text": pending_text, "_message_index": current_message},
                    )
                    pending_text = ""
                await asyncio.sleep(0.1)
        finally:
            if handle is not None and self.supervisor.exit_code(handle) is None:
                await asyncio.to_thread(self.supervisor.kill, handle)
