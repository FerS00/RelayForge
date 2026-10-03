"""Gate fail-closed para llamadas de herramientas durante la auditoría."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.evidence import Evidence  # noqa: E402


def _resolved(path: str) -> Path:
    return Path(path).expanduser().resolve(strict=False)


def decide(policy: dict, tool_call: dict) -> tuple[Literal["allow", "deny"], str]:
    try:
        payload = tool_call["toolCall"]
        if not isinstance(payload, dict):
            return "deny", "toolCall must be an object"
        name = payload["name"]
        args = payload.get("args", {})
        if not isinstance(args, dict):
            return "deny", "tool input must be an object"
        if name in {"view_file", "grep_search"}:
            key = "AbsolutePath" if name == "view_file" else "SearchPath"
            raw = args.get(key)
            if not isinstance(raw, str) or not raw:
                return "deny", f"missing {key}"
            target = _resolved(raw)
            allowed = {_resolved(str(path)) for path in policy["files"]}
            run_dir = _resolved(policy["run_dir"])
            match = re.fullmatch(r"check-(\d+)\.json", target.name)
            check_count = len(policy.get("reviewed_commands", []))
            is_check = target.parent == run_dir and match is not None and int(match.group(1)) < check_count
            if target in allowed or is_check:
                return "allow", "read path is allowlisted"
            return "deny", "read path is not allowlisted"
        if name == "run_command":
            command = args.get("CommandLine")
            cwd = args.get("Cwd")
            persistent = args.get("RunPersistent", False)
            if not isinstance(command, str) or command not in policy["commands"]:
                return "deny", "command is not exactly allowlisted"
            allowed_cwds = {_resolved(policy["workspace"]), _resolved(policy["run_dir"])}
            if not isinstance(cwd, str) or _resolved(cwd) not in allowed_cwds:
                return "deny", "working directory is not allowlisted"
            if persistent is True:
                return "deny", "persistent commands are denied"
            return "allow", "command and working directory are allowlisted"
        if name in {"finish", "wait_5_seconds"}:
            return "allow", "non-mutating control tool"
        return "deny", "unknown tool"
    except Exception as exc:
        return "deny", f"invalid policy or tool input: {type(exc).__name__}"


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        policy = json.loads(args.policy.read_text(encoding="utf-8"))
        call = json.load(sys.stdin)
        decision, reason = decide(policy, call)
    except Exception as exc:
        policy = {"run_dir": str(args.policy.parent)}
        call = {"invalid": type(exc).__name__}
        decision, reason = "deny", f"invalid JSON or policy: {type(exc).__name__}"
    response = {"decision": decision, "reason": reason}
    print(json.dumps(response, ensure_ascii=False))
    try:
        log_path = args.policy.parent / "gate.ndjson"
        previous = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        record = json.dumps({"decision": decision, "reason": reason, "tool": call}, ensure_ascii=False)
        Evidence("gate", args.policy.parent).write_text("gate.ndjson", previous + record + "\n")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
