"""Valida persistencia de aprobaciones y la integración de Claude opcional."""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.binaries import locate  # noqa: E402
from common.evidence import Evidence  # noqa: E402
from common.procs import JobObject, spawn_in_job  # noqa: E402
from common.redact import redact  # noqa: E402


def claude_commands(binary: str, config: str = "<mcp-config>") -> list[list[str]]:
    prefix = [binary, "-p", "--output-format", "stream-json", "--verbose", "--permission-mode",
              "default", "--mcp-config", config,
              "--permission-prompt-tool", "mcp__rfperm__approval_prompt", "--allowed-tools",
              "mcp__rfperm__approval_prompt"]
    return [prefix.copy() for _ in range(3)]


def _start_server(db_path: Path, effects: Path, port: int, evidence: Evidence) -> tuple[JobObject, subprocess.Popen]:
    job = JobObject()
    process = spawn_in_job([sys.executable, str(Path(__file__).with_name("app.py")), "--db", str(db_path),
                            "--effects", str(effects), "--port", str(port)], job, Path(__file__).parent,
                           evidence.dir / "server.stdout", evidence.dir / "server.stderr")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/approvals", timeout=0.3).status_code == 200:
                return job, process
        except httpx.HTTPError:
            time.sleep(0.1)
    job.terminate()
    raise TimeoutError("API no respondió en 10 s")


def _request(client: httpx.Client, method: str, path: str, **kwargs) -> httpx.Response:
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response


def _claude_case(command: list[str], prompt: str, name: str, evidence: Evidence,
                 repo: Path, port: int, timeout: float,
                 decision: str | None) -> tuple[int, list[dict]]:
    prompt_file = evidence.write_text(f"{name}.prompt", prompt)
    stream = evidence.dir / f"{name}.ndjson"
    job = JobObject()
    try:
        proc = spawn_in_job(command, job, repo, stream,
                            evidence.dir / f"{name}.stderr", prompt_file)
        deadline = time.monotonic() + timeout
        seen_requests: set[str] = set()
        request_log = []
        while proc.poll() is None and time.monotonic() < deadline:
            pending = httpx.get(f"http://127.0.0.1:{port}/permission", timeout=2).json()
            for item in pending:
                request_id = str(item["id"])
                if request_id in seen_requests:
                    continue
                seen_requests.add(request_id)
                tool_input = item.get("input", {})
                request_log.append({"case": name, "tool_name": item.get("tool_name"),
                                    "input": tool_input,
                                    "input_keys": sorted(tool_input) if isinstance(tool_input, dict) else []})
                if decision is None:
                    job.terminate()
                    proc.wait(timeout=5)
                    return -1, request_log
                httpx.post(f"http://127.0.0.1:{port}/permission/{request_id}/decision",
                           json={"decision": decision if item.get("tool_name") == "Write" else "deny"},
                           timeout=2).raise_for_status()
            time.sleep(0.2)
        if proc.poll() is None:
            job.terminate()
            proc.wait(timeout=5)
            return -1, request_log
        return proc.returncode, request_log
    finally:
        job.close()


def _events(path: Path) -> list[dict]:
    events = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def _walk_dicts(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _tool_results(events: list[dict]) -> list[dict]:
    return [item for event in events for item in _walk_dicts(event)
            if item.get("type") == "tool_result"]


def _has_permission_denial(events: list[dict]) -> bool:
    if any(bool(item.get("permission_denials")) for event in events for item in _walk_dicts(event)):
        return True
    denial_markers = ("denied", "rejected", '"behavior": "deny"', '"decision": "deny"')
    return any(any(term in json.dumps(item, ensure_ascii=False).casefold()
                   for term in denial_markers) for item in _tool_results(events))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-claude", action="store_true")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)
    binary = locate("claude")
    commands = claude_commands("claude" if args.dry_run else
                               str(binary.path) if binary.path else "claude")
    if args.dry_run:
        print(redact(json.dumps(commands, ensure_ascii=False, indent=2)))
        return 0
    evidence = Evidence("poc08_approval")
    evidence.record_versions()
    repo = args.repo.resolve()
    if not (repo / ".relayforge-sandbox").is_file():
        evidence.verdict("FAIL", [{"id": "C0", "passed": False, "description": "sandbox marcado"}])
        return 2
    if not args.skip_claude and binary.path is None:
        evidence.verdict("FAIL", [{"id": "C0", "passed": False, "description": "Claude instalado"}])
        return 3
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    db_path, effects = evidence.dir / "approvals.sqlite", evidence.dir / "effects"
    server_job: JobObject | None = None
    criteria = []
    try:
        server_job, server_proc = _start_server(db_path, effects, port, evidence)
        base = f"http://127.0.0.1:{port}"
        with httpx.Client(base_url=base, timeout=10) as client:
            j1 = _request(client, "POST", "/jobs", json={"operation": "git.push"}).json()
        server_job.terminate()
        server_job.close()
        server_job = None
        server_job, server_proc = _start_server(db_path, effects, port, evidence)
        with httpx.Client(base_url=base, timeout=10) as client:
            pending = _request(client, "GET", "/approvals", params={"status": "pending"}).json()
            criteria.append({"id": "C1", "passed": any(row["id"] == j1["approval_id"] for row in pending)})
            decision_path = f"/approvals/{j1['approval_id']}/decision"
            payload = {"decision": "approve", "scope": "job"}
            first = _request(client, "POST", decision_path, json=payload,
                             headers={"Idempotency-Key": "K1"}).json()
            repeat = _request(client, "POST", decision_path, json=payload,
                              headers={"Idempotency-Key": "K1"}).json()
            effects_after_repeat = _request(client, "GET", "/effects").json()
            conflict = client.post(decision_path, json=payload, headers={"Idempotency-Key": "K2"})
            auto = _request(client, "POST", f"/jobs/{j1['id']}/request", json={"operation": "git.push"}).json()
            j2 = _request(client, "POST", "/jobs", json={"operation": "git.push"}).json()
            j2_pending = any(row["id"] == j2["approval_id"] and row["status"] == "pending"
                             for row in _request(client, "GET", "/approvals",
                                                 params={"status": "pending"}).json())
            criteria.append({"id": "C6", "passed": j2_pending,
                             "evidence": "J2 pending; el grant no se extiende a otros jobs"})
            rejected = _request(client, "POST", f"/approvals/{j2['approval_id']}/decision",
                                json={"decision": "reject", "scope": "once"},
                                headers={"Idempotency-Key": "K3"}).json()
            effects_rows = _request(client, "GET", "/effects").json()
            criteria.extend([
                {"id": "C2", "passed": first["effect_count"] == 1},
                {"id": "C3", "passed": repeat == first and len(effects_after_repeat) == 1,
                 "evidence": {"response_equal": repeat == first, "effects_after_repeat": len(effects_after_repeat)}},
                {"id": "C4", "passed": conflict.status_code == 409},
                {"id": "C5", "passed": auto["status"] == "approved" and auto["decided_via"] == "grant"},
                {"id": "C7", "passed": rejected["job_status"] == "FAILED" and len(effects_rows) == 2},
            ])
        if not args.skip_claude:
            config_path = evidence.dir / "mcp-config.json"
            config_path.write_text(json.dumps({"mcpServers": {"rfperm": {"type": "stdio",
                "command": sys.executable, "args": ["-X", "utf8", str(Path(__file__).with_name(
                    "permission_tool.py").resolve())], "env": {"RELAYFORGE_API": base}}}}),
                encoding="utf-8", newline="\n")
            case_logs = []
            claude_cases = []
            cases = (
                ("allow", "Usa la herramienta Write para crear el archivo rf-perm-approved.txt "
                 "en el directorio actual con el contenido OK.", "allow"),
                ("deny", "Usa la herramienta Write para crear el archivo rf-perm-denied.txt "
                 "en el directorio actual con el contenido OK.", "deny"),
                ("auto", "Ejecuta en Bash exactamente: echo RF-AUTO", None),
            )
            c10 = None
            for index, (label, prompt, decision) in enumerate(cases):
                case_name = f"claude-{index}-{label}"
                command = claude_commands(str(binary.path), str(config_path))[index]
                code, incoming = _claude_case(command, prompt, case_name, evidence, repo,
                                              port, args.timeout, decision)
                case_logs.extend(incoming)
                events = _events(evidence.dir / f"{case_name}.ndjson")
                init = next((event for event in events if event.get("type") == "system" and
                             event.get("subtype") == "init"), {})
                servers = init.get("mcp_servers", [])
                own = next((item for item in servers if isinstance(item, dict) and
                            item.get("name") == "rfperm"), {})
                connected = own.get("status") == "connected"
                write_requested = any(item.get("tool_name") == "Write" for item in incoming)
                tool_results = _tool_results(events)
                tool_result_text = json.dumps(tool_results, ensure_ascii=False)
                server_evidence = {"name": "rfperm", "status": own.get("status", "missing")}
                if label == "allow":
                    approved_exists = (repo / "rf-perm-approved.txt").is_file()
                    criteria.append({"id": "C8", "passed": connected and write_requested and approved_exists,
                        "write_requested": write_requested, "file_exists": approved_exists,
                        "note": "" if connected else "MCP no conectado",
                        "permission_mode": init.get("permissionMode"),
                        "own_mcp_server": server_evidence})
                elif label == "deny":
                    denied_exists = (repo / "rf-perm-denied.txt").is_file()
                    denial_observed = _has_permission_denial(events)
                    criteria.append({"id": "C9", "passed": connected and write_requested and
                                     not denied_exists and denial_observed,
                        "write_requested": write_requested, "file_exists": denied_exists,
                        "denial_observed": denial_observed,
                        "note": "" if connected else "MCP no conectado",
                        "permission_mode": init.get("permissionMode"),
                        "own_mcp_server": server_evidence})
                else:
                    executed = "RF-AUTO" in tool_result_text
                    c10 = {"id": "C10", "informational": True,
                           "passed": executed and not incoming, "executed": executed,
                           "permission_consulted": bool(incoming),
                           "permission_mode": init.get("permissionMode"),
                           "own_mcp_server": server_evidence}
                claude_cases.append({"case": case_name, "permission_mode": init.get("permissionMode"),
                                     "own_mcp_server": server_evidence, "returncode": code})
            evidence.write_json("permission_inputs.json", case_logs)
            evidence.write_json("claude_cases.json", claude_cases)
            criteria.append(c10)
            config_path.unlink(missing_ok=True)
        else:
            criteria.extend([{"id": "C8", "passed": None, "note": "--skip-claude"},
                             {"id": "C9", "passed": None, "note": "--skip-claude"},
                             {"id": "C10", "passed": None, "informational": True,
                              "note": "--skip-claude"}])
        gating_criteria = [item for item in criteria if not item.get("informational")]
        status = "FAIL" if any(item["passed"] is False for item in gating_criteria) else (
            "MANUAL" if any(item["passed"] is None for item in gating_criteria) else "PASS")
        evidence.verdict(status, criteria)
        return 0 if status != "FAIL" else 1
    except (OSError, RuntimeError, TimeoutError, httpx.HTTPError, subprocess.TimeoutExpired) as exc:
        criteria.append({"id": "execution", "passed": False, "evidence": str(exc)})
        evidence.verdict("FAIL", criteria)
        return 1
    finally:
        for filename in ("rf-perm-approved.txt", "rf-perm-denied.txt"):
            path = repo / filename
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)
        if server_job:
            server_job.terminate()
            server_job.close()


if __name__ == "__main__":
    raise SystemExit(main())
