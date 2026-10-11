from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path

from relayforge.adapters.base import ConversationContext, NormalizedEvent, ParseState
from relayforge.adapters.codex.adapter import CodexAdapter, CodexRunSpec
from relayforge.core.agent_health import classify_failure
from relayforge.process.supervisor import RunHandle, Supervisor


@dataclass
class CodexChat:
    adapter: CodexAdapter
    supervisor: Supervisor
    output_root: Path
    effort: str = "medium"
    timeout_seconds: float = 1800
    structured: bool = False
    sandbox: str = "read-only"
    on_process_started: Callable[[str, RunHandle], None] | None = None

    async def chat(self, ctx: ConversationContext, message: str) -> AsyncIterator[NormalizedEvent]:
        launch = self.adapter.build_run(
            CodexRunSpec(
                ctx.cwd,
                message,
                Path(__file__).resolve().parents[4] / "config/schemas/chat.schema.json"
                if self.structured
                else None,
                resume_thread_id=ctx.session_id if ctx.session_established else None,
                model=ctx.model,
                sandbox=self.sandbox,
                reasoning_effort=ctx.effort or self.effort,
                skip_git_repo_check=True,
                image_paths=ctx.image_paths,
                web_search=ctx.web_search,
            )
        )
        folder = self.output_root / "chat" / ctx.conversation_id / ctx.step_id / uuid.uuid4().hex
        state, handle = ParseState(), None
        started, message_index = time.monotonic(), 0
        try:
            handle = await self.supervisor.start_async(
                launch, output_path=folder / "stdout.ndjson", stderr_path=folder / "stderr.log"
            )
            if self.on_process_started:
                self.on_process_started(ctx.step_id, handle)
            while True:
                if time.monotonic() - started > self.timeout_seconds:
                    raise RuntimeError("chat_timeout")
                lines = await asyncio.to_thread(self.supervisor.read_lines, handle)
                code = await asyncio.to_thread(self.supervisor.exit_code, handle)
                if code is not None:
                    lines.extend(await asyncio.to_thread(self.supervisor.read_lines, handle))
                for line in lines:
                    for event in self.adapter.parse_line(line, state):
                        data = dict(event.data)
                        if event.type == "agent.message":
                            data["_message_index"] = message_index
                            message_index += 1
                        yield NormalizedEvent(event.type, "codex", ctx.step_id, data)
                if code is not None:
                    outcome = (
                        "failed"
                        if code != 0 or state.result_is_error
                        else ("ok" if state.result_seen and message_index else "invalid_output")
                    )
                    detail = classify_failure(state.failure_detail) if outcome == "failed" else None
                    yield NormalizedEvent(
                        "agent.exit",
                        "codex",
                        ctx.step_id,
                        {
                            "outcome": outcome,
                            "detail": detail,
                            "duration_ms": int((time.monotonic() - started) * 1000),
                        },
                    )
                    return
                await asyncio.sleep(0.1)
        finally:
            if isinstance(handle, RunHandle):
                await asyncio.to_thread(self.supervisor.kill, handle)
