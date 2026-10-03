"""Backend de prueba que reconcilia el stream incremental de un agente."""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.binaries import locate  # noqa: E402
from common.procs import JobObject, spawn_in_job  # noqa: E402


def read_new_lines(path: Path, offset: int) -> tuple[list[bytes], int]:
    if not path.exists():
        return [], offset
    with path.open("rb") as stream:
        stream.seek(offset)
        data = stream.read()
    complete = data.split(b"\n")
    if len(complete) == 1:
        return [], offset
    lines = [line for line in complete[:-1] if line.strip()]
    consumed = sum(len(line) + 1 for line in complete[:-1])
    return lines, offset + consumed


def is_final(agent: str, event: dict) -> bool:
    if agent == "claude":
        return event.get("type") == "result"
    return event.get("type") == "turn.completed" or event.get("type") == "turn.failed"


def starts_conversation(agent: str, event: dict) -> bool:
    if agent == "claude":
        return event.get("type") == "assistant"
    return event.get("type") == "item.completed"


def is_not_resumable(agent: str, event: dict) -> bool:
    if agent != "claude" or event.get("type") != "result":
        return False
    if event.get("subtype") != "error_during_execution":
        return False
    errors = event.get("errors")
    return isinstance(errors, list) and any(
        isinstance(error, str) and "No conversation found with session ID:" in error
        for error in errors
    )


def _alive(state: dict) -> bool:
    try:
        process = psutil.Process(int(state["pid"]))
        return abs(process.create_time() - float(state["create_time"])) <= 0.01 and process.is_running()
    except (psutil.NoSuchProcess, psutil.AccessDenied, KeyError, ValueError):
        return False


def _save(state_path: Path, state: dict) -> None:
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def _consume(state_path: Path, state: dict, wait_for_process: bool) -> dict:
    stdout = Path(state["stdout"])
    final_seen = False
    while True:
        lines, new_offset = read_new_lines(stdout, int(state.get("offset", 0)))
        for line in lines:
            try:
                event = json.loads(line.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
            state["lines"] = int(state.get("lines", 0)) + 1
            if starts_conversation(state["agent"], event):
                state["conversation_started"] = True
            if is_not_resumable(state["agent"], event):
                state["status"] = "not_resumable"
                state["resume_error"] = "No conversation found with session ID"
            if state["agent"] == "codex" and not state.get("thread_id") and event.get("type") == "thread.started":
                state["thread_id"] = event.get("thread_id")
            if is_final(state["agent"], event) and state.get("status") != "not_resumable":
                final_seen = True
        state["offset"] = new_offset
        state["heartbeat_at"] = datetime.now(timezone.utc).isoformat()
        if state.get("status") != "not_resumable":
            if final_seen:
                state["status"] = "completed"
            elif not _alive(state):
                state["status"] = "interrupted"
        _save(state_path, state)
        if state["status"] != "running" or not wait_for_process:
            return state
        time.sleep(0.5)


def _agent_argv(agent: str, repo: Path, prompt: Path, resume: str | None = None) -> list[str]:
    binary = locate(agent)
    exe = str(binary.path) if binary.path else agent
    if agent == "claude":
        args = [exe, "-p", "--output-format", "stream-json", "--verbose",
                "--permission-mode", "default"]
        if resume:
            args.extend(["--resume", resume])
        else:
            args.extend(["--session-id", str(uuid.uuid4())])
        return args
    if resume:
        return [exe, "exec", "resume", resume, "-C", str(repo), "-c",
                'sandbox_mode="workspace-write"', "-c", "windows.sandbox='unelevated'", "--json", "-"]
    return [exe, "exec", "--json", "-C", str(repo), "-s", "workspace-write", "-c",
            "windows.sandbox='unelevated'", "-"]


def _launch(agent: str, repo: Path, state_path: Path, prompt_path: Path,
            resume: str | None = None, output_name: str | None = None) -> dict:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    stdout = state_path.parent / (output_name or "agent.ndjson")
    stderr = state_path.parent / (stdout.stem + ".stderr")
    argv = _agent_argv(agent, repo, prompt_path, resume)
    job = JobObject(kill_on_close=False)
    try:
        process = spawn_in_job(argv, job, repo, stdout, stderr, prompt_path)
        created = psutil.Process(process.pid).create_time()
        state = {"agent": agent, "pid": process.pid, "create_time": created, "stdout": str(stdout),
                 "offset": 0, "lines": 0, "conversation_started": False,
                 "started_at": datetime.now(timezone.utc).isoformat(),
                 "status": "running", "repo": str(repo.resolve())}
        if agent == "claude":
            state["session_id"] = next((argv[i + 1] for i, value in enumerate(argv[:-1])
                                        if value == "--session-id"), resume)
        elif resume:
            state["thread_id"] = resume
        _save(state_path, state)
    finally:
        job.close()
    return _consume(state_path, state, True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("--agent", choices=("claude", "codex"), required=True)
    start.add_argument("--repo", type=Path, required=True)
    start.add_argument("--state", type=Path, required=True)
    start.add_argument("--prompt-file", type=Path, required=True)
    resume = sub.add_parser("resume")
    resume.add_argument("--state", type=Path, required=True)
    cont = sub.add_parser("continue")
    cont.add_argument("--state", type=Path, required=True)
    cont.add_argument("--prompt-file", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "start":
        if not (args.repo / ".relayforge-sandbox").is_file():
            return 2
        state = _launch(args.agent, args.repo.resolve(), args.state.resolve(), args.prompt_file.resolve())
    elif args.command == "resume":
        state = json.loads(args.state.read_text(encoding="utf-8"))
        state = _consume(args.state, state, _alive(state))
    else:
        previous = json.loads(args.state.read_text(encoding="utf-8"))
        identity = previous.get("session_id") if previous["agent"] == "claude" else previous.get("thread_id")
        if not identity:
            raise RuntimeError("No hay session_id/thread_id para continuar")
        state = _launch(previous["agent"], Path(previous["repo"]), args.state.resolve(),
                        args.prompt_file.resolve(), identity, "agent-2.ndjson")
    print(json.dumps(state, ensure_ascii=False))
    return 0 if state.get("status") in {"completed", "not_resumable"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
