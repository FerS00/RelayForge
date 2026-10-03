"""Escenarios de supervivencia del agente y recuperación de sesión."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.binaries import locate  # noqa: E402
from common.evidence import Evidence  # noqa: E402
from common.procs import kill_tree_fallback  # noqa: E402
from common.redact import redact  # noqa: E402


def agent_commands(agent: str, repo: Path) -> list[list[str]]:
    exe = str(locate(agent).path) if locate(agent).path else agent
    if agent == "claude":
        return [[exe, "-p", "--output-format", "stream-json", "--verbose", "--permission-mode",
                 "default", "--session-id", str(uuid.uuid4())],
                [exe, "-p", "--output-format", "stream-json", "--verbose", "--permission-mode",
                 "default", "--resume", "<session_id>"]]
    return [[exe, "exec", "--json", "-C", str(repo), "-s", "workspace-write", "-c",
             "windows.sandbox='unelevated'", "-"],
            [exe, "exec", "resume", "<thread_id>", "-C", str(repo), "-c",
             'sandbox_mode="workspace-write"', "-c", "windows.sandbox='unelevated'", "--json", "-"]]


def _read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _invoke_supervisor(command: str, state: Path, prompt: Path | None = None,
                       agent: str | None = None, repo: Path | None = None,
                       timeout: float = 620) -> tuple[int, str]:
    script = Path(__file__).with_name("supervisor.py")
    args = [sys.executable, str(script), command]
    if command == "start":
        args.extend(["--agent", str(agent), "--repo", str(repo), "--state", str(state),
                     "--prompt-file", str(prompt)])
    else:
        args.extend(["--state", str(state)])
        if prompt:
            args.extend(["--prompt-file", str(prompt)])
    result = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    return result.returncode, result.stdout.decode("utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--agent", choices=("claude", "codex"), default="claude")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)
    commands = agent_commands(args.agent, args.repo.resolve())
    if args.dry_run:
        for command in commands:
            command[0] = args.agent
        print(redact(json.dumps(commands, ensure_ascii=False, indent=2)))
        return 0
    evidence = Evidence("poc07_backend_restart")
    evidence.record_versions()
    repo = args.repo.resolve()
    if not (repo / ".relayforge-sandbox").is_file():
        evidence.verdict("FAIL", [{"id": "C0", "passed": False, "description": "sandbox marcado"}])
        return 2
    if locate(args.agent).path is None:
        evidence.verdict("FAIL", [{"id": "C0", "passed": False, "description": "agente instalado"}])
        return 3
    worktree: Path | None = None
    branch: str | None = None
    agent_pids: set[int] = set()
    criteria = []
    try:
        if args.agent == "codex":
            stamp = time.strftime("%Y%m%d-%H%M%S")
            worktree = evidence.dir / "codex-worktree"
            branch = f"poc/poc07-{stamp}"
            made = subprocess.run(["git", "-C", str(repo), "worktree", "add", "-b", branch,
                                   str(worktree), "HEAD"], capture_output=True, timeout=60, check=False)
            if made.returncode:
                raise RuntimeError(made.stderr.decode("utf-8", errors="replace"))
            repo = worktree
        scenarios = ("A", "B", "B-early") if args.agent == "claude" else ("A", "B")
        for scenario in scenarios:
            scenario_dir = evidence.dir / scenario
            scenario_dir.mkdir(parents=True, exist_ok=True)
            state_path = scenario_dir / "state.json"
            first_prompt = evidence.write_text(f"scenario-{scenario}.prompt",
                "Lee calc/ops.py y escribe un análisis de unas 600 palabras.\n" if scenario == "A" else
                "Recuerda la palabra VERDE-42. Luego lee calc/ops.py y escribe un análisis de 600 palabras.\n")
            supervisor = subprocess.Popen([sys.executable, str(Path(__file__).with_name("supervisor.py")),
                "start", "--agent", args.agent, "--repo", str(repo), "--state", str(state_path),
                "--prompt-file", str(first_prompt)], cwd=repo, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                state = _read_state(state_path)
                if state.get("pid"):
                    agent_pids.add(int(state["pid"]))
                if scenario == "A" and state.get("lines", 0) >= 3:
                    break
                if scenario == "B" and state.get("conversation_started"):
                    break
                if scenario == "B-early" and state.get("lines", 0) >= 3 and not state.get("conversation_started"):
                    break
                if supervisor.poll() is not None:
                    raise RuntimeError(f"supervisor {scenario} terminó antes del disparador de corte")
                time.sleep(0.1)
            else:
                raise TimeoutError(f"scenario {scenario}: no se recibió el disparador de corte")
            state = _read_state(state_path)
            if scenario == "A":
                try:
                    psutil.Process(supervisor.pid).kill()
                except psutil.NoSuchProcess:
                    pass
                from poc07_backend_restart.supervisor import _alive
                alive = _alive(state)
                criteria.append({"id": "C1", "passed": alive, "evidence": "agente continúa tras matar supervisor"})
                code, output = _invoke_supervisor("resume", state_path, timeout=args.timeout + 20)
                state = _read_state(state_path)
                output_path = Path(state["stdout"])
                complete_lines = sum(1 for line in output_path.read_bytes().splitlines() if line.strip())
                passed = code == 0 and state.get("status") == "completed" and state.get("lines") == complete_lines
                criteria.append({"id": "C2", "passed": passed,
                                 "evidence": {"status": state.get("status"), "state_lines": state.get("lines"),
                                              "file_lines": complete_lines, "resume_output": output}})
            elif scenario == "B":
                try:
                    psutil.Process(supervisor.pid).kill()
                    supervisor.wait(timeout=5)
                except (psutil.NoSuchProcess, subprocess.TimeoutExpired):
                    pass
                try:
                    kill_tree_fallback(int(state["pid"]))
                except (KeyError, ValueError):
                    pass
                code, _ = _invoke_supervisor("resume", state_path, timeout=30)
                state = _read_state(state_path)
                criteria.append({"id": "C3", "passed": code == 1 and state.get("status") == "interrupted",
                                 "evidence": {"status": state.get("status"), "resume_returncode": code}})
                continue_prompt = evidence.write_text("scenario-B-continue.prompt",
                    "¿Cuál era la palabra que debías recordar? Responde solo la palabra.\n")
                code, output = _invoke_supervisor("continue", state_path, continue_prompt,
                                                  timeout=args.timeout + 20)
                stream = Path(state["stdout"]).parent / "agent-2.ndjson"
                criteria.append({"id": "C4", "passed": code == 0 and
                                 "VERDE-42" in stream.read_text(encoding="utf-8", errors="replace"),
                                 "evidence": output})
            else:
                try:
                    psutil.Process(supervisor.pid).kill()
                    supervisor.wait(timeout=5)
                except (psutil.NoSuchProcess, subprocess.TimeoutExpired):
                    pass
                try:
                    kill_tree_fallback(int(state["pid"]))
                except (KeyError, ValueError):
                    pass
                code, _ = _invoke_supervisor("resume", state_path, timeout=30)
                state = _read_state(state_path)
                interrupted = code == 1 and state.get("status") == "interrupted"
                continue_prompt = evidence.write_text("scenario-B-early-continue.prompt",
                    "Continúa la conversación. Responde solo OK.\n")
                code, output = _invoke_supervisor("continue", state_path, continue_prompt, timeout=30)
                state = _read_state(state_path)
                stream = scenario_dir / "agent-2.ndjson"
                output_text = stream.read_text(encoding="utf-8", errors="replace") if stream.exists() else ""
                no_conversation = "No conversation found with session ID:" in output_text
                criteria.append({"id": "C3b", "passed": interrupted and no_conversation and
                                 state.get("status") == "not_resumable" and code == 0,
                                 "evidence": {"resume_status": "interrupted" if interrupted else state.get("status"),
                                              "continue_status": state.get("status"),
                                              "no_conversation_found": no_conversation, "continue_output": output}})
        alive_pids = []
        for pid in agent_pids:
            if psutil.pid_exists(pid):
                alive_pids.append(pid)
                kill_tree_fallback(pid)
        criteria.append({"id": "C5", "passed": not alive_pids, "leftover_pids": alive_pids})
        status = "PASS" if all(item["passed"] for item in criteria) else "FAIL"
        evidence.verdict(status, criteria)
        return 0 if status == "PASS" else 1
    except (OSError, RuntimeError, subprocess.TimeoutExpired, TimeoutError, KeyError, ValueError) as exc:
        criteria.append({"id": "execution", "passed": False, "evidence": str(exc)})
        evidence.verdict("FAIL", criteria)
        return 1
    finally:
        for pid in agent_pids:
            if psutil.pid_exists(pid):
                kill_tree_fallback(pid)
        if worktree and branch:
            subprocess.run(["git", "-C", str(args.repo.resolve()), "worktree", "remove", "--force",
                            str(worktree)], capture_output=True, timeout=60, check=False)
            subprocess.run(["git", "-C", str(args.repo.resolve()), "branch", "-D", branch],
                           capture_output=True, timeout=60, check=False)


if __name__ == "__main__":
    raise SystemExit(main())
