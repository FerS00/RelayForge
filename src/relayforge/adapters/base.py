from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class RunSpec:
    session_id: str
    resume: bool
    cwd: Path
    prompt: str


@dataclass(frozen=True)
class LaunchPlan:
    argv: tuple[str, ...]
    cwd: Path
    stdin_text: str
    env: Mapping[str, str] | None = None


@dataclass
class ParseState:
    unparsed_lines: int = 0
    result_seen: bool = False
    result_is_error: bool = False


@dataclass(frozen=True)
class NormalizedEvent:
    type: str
    actor: str
    step_id: str | None
    data: dict[str, Any]
    ts: str | None = None


RunOutcome = Literal["ok", "failed", "invalid_output", "start_failed", "server_shutdown"]


class AgentAdapter(Protocol):
    name: str

    def build_run(self, spec: RunSpec) -> LaunchPlan: ...

    def parse_line(self, line: bytes, state: ParseState) -> list[NormalizedEvent]: ...

    def classify_exit(self, code: int, state: ParseState) -> RunOutcome: ...


@dataclass(frozen=True)
class ConversationContext:
    conversation_id: str
    session_id: str
    session_established: bool
    cwd: Path
    step_id: str = ""


class OrchestratorAdapter(Protocol):
    name: str

    def chat(self, ctx: ConversationContext, message: str) -> AsyncIterator[NormalizedEvent]: ...
