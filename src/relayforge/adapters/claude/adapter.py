from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from relayforge.adapters.base import LaunchPlan, NormalizedEvent, ParseState, RunOutcome, RunSpec
from relayforge.adapters.claude.parser import parse_line

_DENIED = (
    "Bash(codex:*)",
    "Bash(codex *)",
    "Bash(agy:*)",
    "Bash(agy *)",
    "Bash",
    "Write",
    "Edit",
    "MultiEdit",
    "NotebookEdit",
)


@dataclass(frozen=True)
class ClaudeAdapter:
    executable: str = "claude"
    model: str = ""
    name: str = "claude"

    def build_run(self, spec: RunSpec) -> LaunchPlan:
        argv = [self.executable, "-p", "--output-format", "stream-json", "--verbose"]
        argv.extend(["--resume", spec.session_id] if spec.resume else ["--session-id", spec.session_id])
        if self.model:
            argv.extend(["--model", self.model])
        argv.extend(
            ["--include-partial-messages", "--permission-mode", "default", "--disallowed-tools", *_DENIED]
        )
        return LaunchPlan(tuple(argv), Path(spec.cwd), spec.prompt)

    def parse_line(self, line: bytes, state: ParseState) -> list[NormalizedEvent]:
        return parse_line(line, state)

    def classify_exit(self, code: int, state: ParseState) -> RunOutcome:
        if code != 0 or state.result_is_error:
            return "failed"
        if not state.result_seen:
            return "invalid_output"
        return "ok"
