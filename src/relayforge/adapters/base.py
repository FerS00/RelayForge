from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol


@dataclass(frozen=True)
class RunSpec:
    session_id: str
    resume: bool
    cwd: Path
    prompt: str
    schema_path: Path | None = None
    model: str = ""


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
    structured_output: Any = None
    failure_detail: str = ""
    usage: dict[str, int] = field(default_factory=dict)


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
    model: str = ""


@dataclass(frozen=True)
class PlanResult:
    objective: str
    summary: str
    steps: tuple[str, ...]
    risks: tuple[str, ...]
    suggested_workflow: Literal["trivial", "feature", "security"] = "feature"


@dataclass(frozen=True)
class FindingInput:
    external_id: str
    severity: str
    file: str
    line: int | None
    title: str
    evidence: str
    recommendation: str


@dataclass(frozen=True)
class TriageDecision:
    finding_id: str
    decision: Literal["accept", "reject", "defer"]
    reason: str


@dataclass(frozen=True)
class TriageResult:
    decisions: tuple[TriageDecision, ...]


@dataclass(frozen=True)
class AuditResult:
    verdict: Literal["APPROVED", "APPROVED_WITH_NOTES", "REJECTED", "BLOCKED"]
    summary: str
    findings: tuple[FindingInput, ...]
    hashes_before: dict[str, str | None]
    hashes_after: dict[str, str | None]


class OrchestratorAdapter(Protocol):
    name: str

    async def plan(self, ctx: ConversationContext, request_text: str) -> PlanResult: ...

    async def triage(
        self,
        ctx: ConversationContext,
        findings: list[dict[str, Any]],
        diff: str,
        test_results: list[dict[str, Any]],
    ) -> TriageResult: ...

    def chat(self, ctx: ConversationContext, message: str) -> AsyncIterator[NormalizedEvent]: ...


class PlannerAdapter(Protocol):
    async def plan(self, ctx: ConversationContext, request_text: str) -> PlanResult: ...

    async def triage(
        self,
        ctx: ConversationContext,
        findings: list[dict[str, Any]],
        diff: str,
        test_results: list[dict[str, Any]],
    ) -> TriageResult: ...
