"""Prueba MCP, restricciones de Bash y delegación de Claude."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.binaries import locate  # noqa: E402
from common.evidence import Evidence  # noqa: E402
from common.procs import JobObject, spawn_in_job  # noqa: E402
from common.redact import redact  # noqa: E402

PROMPTS = {
    "tools": "Usa get_job_status para JOB-000001 y después propose_job con repo=sandbox, title=Prueba, request=Nada. Responde con estado y proposal_id.",
    "bash_deny": "Ejecuta en Bash exactamente estos dos comandos por separado: `echo RF-ECHO-OK` y `codex --version`. Informa la salida de cada uno.",
    "skill_delegation": "Delega en Codex la tarea de añadir un docstring a calc.add usando la skill codex-delegate.",
}


def case_argv(binary: str, case: str, config: str = "<mcp-config>",
              deny_pattern: str = "Bash(codex:*)") -> list[str]:
    argv = [binary, "-p", "--output-format", "stream-json", "--verbose", "--permission-mode",
            "default", "--mcp-config", config]
    if case == "tools":
        argv.extend(["--allowed-tools", "mcp__relayforge__get_job_status", "mcp__relayforge__propose_job"])
    elif case == "bash_deny":
        argv.extend(["--allowed-tools", "Bash", "--disallowed-tools", deny_pattern])
    else:
        argv.extend(["--allowed-tools", "Bash", "Skill", "Read", "--disallowed-tools",
                     "Bash(codex:*)", "Bash(codex *)", "Bash(agy:*)", "Bash(agy *)",
                     "--append-system-prompt",
                     "Estás dentro de RelayForge (RELAYFORGE_JOB_ID=JOB-000001). La delegación a otros agentes solo ocurre mediante las herramientas relayforge. No uses las skills codex-delegate ni antigravity-audit."])
    return argv


def _events(path: Path) -> list[dict]:
    result = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                value = json.loads(line)
                if isinstance(value, dict):
                    result.append(value)
            except json.JSONDecodeError:
                continue
    return result


def _text(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--case", choices=("all", "tools", "bash_deny", "skill_delegation"), default="all")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)
    binary = locate("claude")
    binary_arg = ("claude" if args.dry_run else str(binary.path) if binary.path else "claude")
    selected = ["tools", "bash_deny", "skill_delegation"] if args.case == "all" else [args.case]
    commands = {name: ([case_argv(binary_arg, name, deny_pattern=pattern)
                        for pattern in ("Bash(codex:*)", "Bash(codex *)")]
                        if name == "bash_deny" else case_argv(binary_arg, name)) for name in selected}
    if args.dry_run:
        for value in commands.values():
            argv_sets = value if value and isinstance(value[0], list) else [value]
            for command in argv_sets:
                if "--append-system-prompt" in command:
                    index = command.index("--append-system-prompt") + 1
                    if index < len(command):
                        command[index] = "<system-prompt>"
        print(redact(json.dumps(commands, ensure_ascii=False, indent=2)))
        return 0
    evidence = Evidence("poc04_mcp_tools")
    evidence.record_versions()
    repo = args.repo.resolve()
    if not (repo / ".relayforge-sandbox").is_file():
        evidence.verdict("FAIL", [{"id": "C0", "description": "sandbox marcado", "passed": False}])
        return 2
    if binary.path is None:
        evidence.verdict("FAIL", [{"id": "C0", "description": "Claude instalado", "passed": False}])
        return 3
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    token = secrets.token_hex(32)
    token_path = evidence.dir / "token.txt"
    config_path = evidence.dir / "mcp-config.json"
    api_log = evidence.dir / "api.ndjson"
    api_job: JobObject | None = None
    api_proc: subprocess.Popen | None = None
    case_results = []
    try:
        token_path.write_text(token, encoding="utf-8", newline="\n")
        config = {"mcpServers": {"relayforge": {"type": "stdio", "command": sys.executable,
                  "args": ["-X", "utf8", str(Path(__file__).with_name("mcp_shim.py").resolve())],
                  "env": {"RELAYFORGE_API": f"http://127.0.0.1:{port}", "RELAYFORGE_JOB_TOKEN": token}}}}
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        evidence.write_json("mcp-config.redacted.json", {"mcpServers": {"relayforge": {"type": "stdio",
                          "command": sys.executable, "args": ["-X", "utf8", "mcp_shim.py"],
                          "env": {"RELAYFORGE_API": f"http://127.0.0.1:{port}",
                                  "RELAYFORGE_JOB_TOKEN": "<redacted>"}}}})
        api_job = JobObject()
        api_proc = spawn_in_job([sys.executable, str(Path(__file__).with_name("local_api.py")),
                                 "--port", str(port), "--token-file", str(token_path), "--log", str(api_log)],
                                api_job, Path(__file__).parent, evidence.dir / "api.stdout",
                                evidence.dir / "api.stderr")
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.3).close()
                break
            except (urllib.error.URLError, TimeoutError):
                if api_proc.poll() is not None:
                    raise RuntimeError("API terminó antes de estar lista")
                time.sleep(0.1)
        else:
            raise TimeoutError("API no respondió en 10 s")
        for name in selected:
            subcases = ["Bash(codex:*)", "Bash(codex *)"] if name == "bash_deny" else [None]
            for subcase in subcases:
                command = case_argv(str(binary.path), name, str(config_path),
                                    subcase or "Bash(codex:*)")
                prompt = evidence.write_text(f"{name}-{len(case_results) + 1}.prompt", PROMPTS[name])
                event_path = evidence.dir / f"{name}-{len(case_results) + 1}.ndjson"
                env = os.environ.copy()
                if name == "skill_delegation":
                    env["RELAYFORGE_JOB_ID"] = "JOB-000001"
                with JobObject() as job:
                    proc = spawn_in_job(command, job, repo, event_path,
                                        evidence.dir / f"{event_path.stem}.stderr", prompt, env)
                    try:
                        code = proc.wait(timeout=args.timeout)
                    except subprocess.TimeoutExpired:
                        job.terminate()
                        proc.wait(timeout=5)
                        code = -1
                events = _events(event_path)
                result = next((item for item in events if item.get("type") == "result"), {})
                init = next((item for item in events if item.get("type") == "system" and
                             item.get("subtype") == "init"), {})
                tools = [block.get("name") for event in events if event.get("type") == "assistant"
                         for block in event.get("message", {}).get("content", [])
                         if isinstance(block, dict) and block.get("type") == "tool_use"]
                content = _text(events)
                denials = result.get("permission_denials", [])
                if name == "tools":
                    api_rows = [json.loads(line) for line in api_log.read_text(encoding="utf-8").splitlines()]
                    c1 = all(any(row["path"].endswith(endpoint) and row["auth_ok"] for row in api_rows)
                             for endpoint in ("get_job_status", "propose_job"))
                    c2 = "IMPLEMENTING" in content and "PROP-" in content
                    servers = init.get("mcp_servers", [])
                    own_server = next((item for item in servers if isinstance(item, dict) and
                                       item.get("name") == "relayforge"), {})
                    relay_status = own_server.get("status")
                    others = sum(item.get("name") != "relayforge" for item in servers
                                 if isinstance(item, dict))
                    criteria = [{"id": "C1", "passed": c1}, {"id": "C2", "passed": c2},
                                {"id": "C3", "passed": False if relay_status != "connected" else
                                 True if others else None,
                                 "note": "MCP no conectado" if relay_status != "connected" else
                                 "sin otros servidores MCP anunciados" if not others else ""}]
                elif name == "bash_deny":
                    tool_results = _text([event for event in events if event.get("type") in {"user", "tool_result"}])
                    c4 = "RF-ECHO-OK" in tool_results
                    c5 = "codex-cli" not in _text([event for event in events if event.get("type") == "tool_result"])
                    c5 = c5 and "codex" in _text(denials).lower()
                    criteria = [{"id": "C4", "passed": c4}, {"id": "C5", "passed": c5,
                                 "syntax": subcase}]
                else:
                    tool_results = _text([event for event in events if event.get("type") == "tool_result"])
                    c6 = not any(signature in tool_results for signature in
                                 ("codex-cli", "OpenAI Codex v", "session id:"))
                    criteria = [{"id": "C6", "passed": c6,
                                 "skill_invoked": "Skill" in tools,
                                 "bash_agent_attempt": any("codex" in _text(item).lower() or
                                                            "agy" in _text(item).lower() for item in denials)}]
                case_results.append({"case": name, "subcase": subcase, "argv": command,
                                     "returncode": code, "tools": tools,
                                     "permission_mode": init.get("permissionMode"),
                                     "own_mcp_server": {"name": "relayforge", "status": next(
                                         (item.get("status") for item in init.get("mcp_servers", [])
                                          if isinstance(item, dict) and item.get("name") == "relayforge"),
                                         "missing")},
                                     "permission_denials": denials, "criteria": criteria})
        evidence.write_json("cases.json", case_results)
        if api_log.exists():
            evidence.write_text("api.ndjson", api_log.read_text(encoding="utf-8", errors="replace"))
        token_path.unlink(missing_ok=True)
        config_path.unlink(missing_ok=True)
        leaked = any(token in path.read_text(encoding="utf-8", errors="replace")
                     for path in evidence.dir.rglob("*") if path.is_file())
        flat = [criterion for case in case_results for criterion in case["criteria"]]
        flat.append({"id": "CS", "passed": not leaked})
        status = "FAIL" if any(item.get("passed") is False for item in flat) else (
            "MANUAL" if any(item.get("passed") is None for item in flat) else "PASS")
        evidence.verdict(status, flat)
        return 0 if status != "FAIL" else 1
    finally:
        if api_job:
            api_job.terminate()
            api_job.close()
        elif api_proc and api_proc.poll() is None:
            api_proc.kill()
        token_path.unlink(missing_ok=True)
        config_path.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
