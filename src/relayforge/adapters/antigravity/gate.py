from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Literal


def decide(policy: dict[str, Any], call: dict[str, Any]) -> tuple[Literal["allow", "deny"], str]:
    try:
        tool = call["toolCall"]
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str):
            return "deny", "invalid tool call"
        name, args = tool["name"], tool.get("args", {})
        if not isinstance(args, dict):
            return "deny", "tool arguments must be an object"
        root = Path(policy["worktree"]).resolve(strict=True)
        if name in {"view_file", "grep_search"}:
            raw_path = args.get("AbsolutePath" if name == "view_file" else "SearchPath")
            if not isinstance(raw_path, str) or not raw_path:
                return "deny", "missing read path"
            path = Path(raw_path)
            allowed = {str(Path(item).resolve(strict=False)) for item in policy["files"]}
            if str(path.resolve(strict=False)) not in allowed:
                return "deny", "read path is not allowlisted"
            return "allow", "read path is allowlisted"
        if name == "run_command":
            command, cwd = args.get("CommandLine"), args.get("Cwd")
            allowed_dispatch = policy.get("dispatch_commands", {})
            if not isinstance(command, str) or command not in allowed_dispatch:
                return "deny", "command is not exactly allowlisted"
            if not isinstance(cwd, str) or Path(cwd).resolve(strict=False) != root:
                return "deny", "working directory is not allowlisted"
            if args.get("RunPersistent") is True:
                return "deny", "persistent commands are denied"
            return "allow", "command and working directory are allowlisted"
        if name in {"finish", "wait_5_seconds"}:
            return "allow", "non-mutating control tool"
        return "deny", "unknown tool"
    except Exception as exc:
        return "deny", f"invalid policy or call: {type(exc).__name__}"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="relayforge gate")
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--dispatch")
    args = parser.parse_args(argv)
    if args.dispatch:
        return dispatch(args.policy, args.dispatch)
    try:
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
        call = json.load(sys.stdin)
        if not isinstance(policy, dict) or not isinstance(call, dict):
            raise ValueError("invalid_payload")
        decision, reason = decide(policy, call)
    except Exception as exc:
        decision, reason = "deny", f"invalid policy or call: {type(exc).__name__}"
    print(json.dumps({"decision": decision, "reason": reason}, ensure_ascii=False))
    try:
        with (args.policy.parent / "gate.ndjson").open("a", encoding="utf-8") as log:
            log.write(json.dumps({"decision": decision, "reason": reason}, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return 0


def dispatch(policy_path: Path, command: str) -> int:
    try:
        policy = json.loads(policy_path.read_text(encoding="utf-8"))
        root = Path(policy["worktree"]).resolve(strict=True)
        from relayforge.adapters.checks import ChecksAdapter
        from relayforge.core.checks import _MAX_OUTPUT_BYTES
        from relayforge.process.supervisor import Supervisor

        parsed = ChecksAdapter.parse_many([policy["commands"][command]])
        if len(parsed) != 1 or parsed[0].name != command:
            return 126
        check = parsed[0]
        plan = ChecksAdapter.build_run(check, root)
        supervisor = Supervisor()
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="relayforge-audit-check-") as raw:
            folder = Path(raw)
            output, error = folder / "stdout.log", folder / "stderr.log"
            handle = supervisor.start(plan, output_path=output, stderr_path=error)
            try:
                while supervisor.exit_code(handle) is None:
                    if output.stat().st_size + error.stat().st_size > _MAX_OUTPUT_BYTES:
                        raise ValueError("check_output_limit")
                    if time.monotonic() - started > check.timeout_seconds:
                        raise subprocess.TimeoutExpired(check.argv, check.timeout_seconds)
                    time.sleep(0.05)
                code = supervisor.exit_code(handle)
                if code is None or output.stat().st_size + error.stat().st_size > _MAX_OUTPUT_BYTES:
                    raise ValueError("check_result_invalid")
                output_text = output.read_text(encoding="utf-8", errors="replace")
                counts = ChecksAdapter.junit_counts(root, check.argv)
                if counts is None:
                    counts = ChecksAdapter.summarize_output(output_text)
            finally:
                supervisor.kill(handle)
        print(
            json.dumps(
                {
                    "exit_code": code,
                    "status": "passed" if code == 0 else "failed",
                    "counts": counts,
                    "duration_seconds": round(time.monotonic() - started, 3),
                },
                ensure_ascii=False,
            )
        )
        return 0 if code == 0 else 1
    except (KeyError, OSError, ValueError, subprocess.TimeoutExpired):
        return 126
