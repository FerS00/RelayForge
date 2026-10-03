"""Sonda de entorno, autenticación de agentes y Git para POC-10."""

from __future__ import annotations

import argparse
import ctypes
import getpass
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Mapping

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.binaries import locate  # noqa: E402
from common.procs import JobObject, spawn_in_job  # noqa: E402
from common.redact import redact  # noqa: E402


def _json_lines(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    if not events:
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                events.append(value)
                break
    return events


def claude_auth_result(returncode: int | None, output: str) -> tuple[str, dict]:
    del returncode
    for event in _json_lines(output):
        if event.get("loggedIn") is True:
            return "AVAILABLE", {"loggedIn": True}
        if event.get("loggedIn") is False:
            return "AUTH_REQUIRED", {"loggedIn": False}
    return "UNKNOWN", {}


def codex_auth_result(returncode: int | None, output: str) -> tuple[str, str]:
    first_line = redact(output.splitlines()[0].strip()) if output.splitlines() else ""
    normalized = first_line.casefold()
    if returncode == 1 or normalized.startswith("not logged in"):
        return "AUTH_REQUIRED", first_line
    if returncode == 0 and normalized.startswith("logged in"):
        return "AVAILABLE", first_line
    return "UNKNOWN", first_line


def claude_result(output: str) -> dict:
    for event in _json_lines(output):
        if event.get("type") == "result":
            return {"event": "result", "is_error": bool(event.get("is_error")),
                    "result_nonempty": bool(str(event.get("result", "")).strip())}
    return {"event": None, "is_error": None, "result_nonempty": False}


def codex_result(output: str) -> dict:
    events = _json_lines(output)
    for event in events:
        if event.get("type") == "turn.completed":
            message = ""
            for item_event in events:
                item = item_event.get("item")
                if item_event.get("type") == "item.completed" and isinstance(item, dict) and \
                        item.get("type") == "agent_message":
                    message = str(item.get("text", ""))
            return {"event": "turn.completed", "result_nonempty": bool(message.strip())}
    return {"event": None, "result_nonempty": False}


def agy_result(output: str) -> dict:
    for event in _json_lines(output):
        result = event.get("result")
        if event.get("event") == "result" and isinstance(result, dict):
            response = result.get("response")
            return {"event": "result", "status": result.get("status"),
                    "result_nonempty": isinstance(response, str) and bool(response.strip())}
    return {"event": None, "status": None, "result_nonempty": False}


def _session_id() -> int | None:
    if os.name != "nt":
        return None
    session = ctypes.c_ulong()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.ProcessIdToSessionId.argtypes = [ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong)]
    kernel32.ProcessIdToSessionId.restype = ctypes.c_int
    if not kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)):
        return None
    return int(session.value)


def _environment(binary_paths: dict[str, str | None]) -> dict:
    result = {}
    for key in ("USERNAME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "PATH"):
        value = os.environ.get(key, "")
        paths = value.split(os.pathsep) if key == "PATH" else [value]
        result[key] = {"present": bool(value), "length": len(value),
                       "contains_agent_bins": any(
                           binary and Path(binary).parent.as_posix().casefold() in
                           {Path(entry).as_posix().casefold() for entry in paths if entry}
                           for binary in binary_paths.values()) if key == "PATH" else None}
    return result


def _context(binary_paths: dict[str, str | None]) -> dict:
    profile = os.environ.get("USERPROFILE")
    return {"whoami": getpass.getuser(), "userprofile_exists": bool(profile and Path(profile).is_dir()),
            "session_id": _session_id(), "environment": _environment(binary_paths),
            "uptime_seconds": max(0, int(time.time() - psutil.boot_time()))}


def _run(command: list[str], cwd: Path, timeout: float, stdin_text: str | None = None,
         env: Mapping[str, str] | None = None) -> dict:
    with TemporaryDirectory(prefix="relayforge-poc10-") as temporary:
        root = Path(temporary)
        stdout_path, stderr_path = root / "stdout.txt", root / "stderr.txt"
        stdin_path = root / "stdin.txt" if stdin_text is not None else None
        if stdin_path is not None:
            stdin_path.write_text(stdin_text, encoding="utf-8")
        try:
            with JobObject() as job:
                process = spawn_in_job(command, job, cwd, stdout_path, stderr_path,
                                        stdin_path=stdin_path, env=env)
                try:
                    returncode = process.wait(timeout=timeout)
                    timed_out = False
                except subprocess.TimeoutExpired:
                    job.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    returncode, timed_out = None, True
            stdout = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
            stderr = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""
            return {"returncode": returncode, "output": redact(stdout + stderr), "timed_out": timed_out}
        except (OSError, NotImplementedError) as exc:
            return {"returncode": None, "output": redact(str(exc)), "timed_out": False}


def _deep_command(agent: str, binary: str, cwd: Path) -> tuple[list[str], str | None]:
    prompt = "Responde solo OK. No ejecutes comandos."
    if agent == "claude":
        return [binary, "-p", "--output-format", "stream-json", "--verbose"], "Responde solo OK"
    if agent == "codex":
        return [binary, "exec", "--json", "--skip-git-repo-check", "-s", "read-only", "-C",
                str(cwd), "-"], "Responde solo OK"
    return [binary, "-p", prompt, "--output-format", "stream-json", "--print-timeout", "60s"], None


def _commands(binary_names: dict[str, str], out_dir: Path, deep: bool,
              git_remote: str | None, label: str) -> dict:
    commands: dict[str, object] = {"label": label}
    for agent, binary in binary_names.items():
        if agent == "claude":
            commands[agent] = {"version": [binary, "--version"], "auth": [binary, "auth", "status"],
                               **({"deep": [binary, "-p", "--output-format", "stream-json", "--verbose",
                                             "<prompt via stdin>"]} if deep else {})}
        elif agent == "codex":
            commands[agent] = {"version": [binary, "--version"], "auth": [binary, "login", "status"],
                               **({"deep": [binary, "exec", "--json", "--skip-git-repo-check", "-s",
                                             "read-only", "-C", str(out_dir), "-"]} if deep else {})}
        else:
            commands[agent] = {"version": [binary, "--version"],
                               **({"deep": [binary, "-p", "<prompt>", "--output-format", "stream-json",
                                             "--print-timeout", "60s"]} if deep else {})}
    if git_remote:
        commands["git_remote"] = ["git", "ls-remote", "--heads", git_remote]
    return commands


def _label(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", value):
        raise argparse.ArgumentTypeError("label debe tener 1-32 caracteres: letras, números, _ o -")
    return value


def write_evidence(out_dir: Path, label: str, payload: str,
                   now: datetime | None = None, pid: int | None = None) -> Path:
    timestamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    process_id = os.getpid() if pid is None else pid
    stem = f"{timestamp}-{label}-{process_id}"
    for attempt in range(1, 21):
        suffix = "" if attempt == 1 else f"-{attempt}"
        output_path = out_dir / f"{stem}{suffix}.json"
        try:
            with output_path.open("x", encoding="utf-8", newline="\n") as evidence_file:
                evidence_file.write(payload)
                evidence_file.write("\n")
            return output_path
        except FileExistsError:
            continue
    raise OSError(f"No se pudo crear un archivo de evidencia único para {stem}")


def run_probe(out_dir: Path, deep: bool, git_remote: str | None) -> dict:
    found = {name: locate(name) for name in ("claude", "codex", "agy")}
    binary_paths = {name: str(value.path) if value.path else None for name, value in found.items()}
    result: dict = {"context": _context(binary_paths), "agents": {}}
    for agent, binary in binary_paths.items():
        row = {"installed": binary is not None, "version": None, "auth": "UNKNOWN"}
        if binary:
            version = _run([binary, "--version"], out_dir, 30)
            row["version"] = redact(version["output"].splitlines()[0]) if version["output"] else None
            if agent == "claude":
                auth_result = _run([binary, "auth", "status"], out_dir, 30)
                row["auth"], evidence = claude_auth_result(auth_result["returncode"], auth_result["output"])
                row["auth_evidence"] = evidence
            elif agent == "codex":
                auth_result = _run([binary, "login", "status"], out_dir, 30)
                row["auth"], evidence = codex_auth_result(auth_result["returncode"], auth_result["output"])
                row["auth_evidence"] = evidence
            if deep:
                command, stdin_text = _deep_command(agent, binary, out_dir)
                deep_result = _run(command, out_dir, 120, stdin_text)
                parsed = (claude_result if agent == "claude" else codex_result if agent == "codex"
                          else agy_result)(deep_result["output"])
                row["deep"] = {"returncode": deep_result["returncode"],
                               "timed_out": deep_result["timed_out"], **parsed}
                if agent == "agy":
                    row["auth"] = ("AVAILABLE" if parsed.get("status") == "SUCCESS" and
                                   parsed.get("result_nonempty") else "UNKNOWN")
        else:
            row["auth"] = "MISSING"
        result["agents"][agent] = row

    if git_remote:
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GCM_INTERACTIVE"] = "never"
        remote = _run(["git", "ls-remote", "--heads", git_remote], out_dir, 60, env=env)
        remote["credentials_error"] = bool(remote["returncode"] and any(
            marker in remote["output"].casefold() for marker in
            ("authentication failed", "could not read username", "terminal prompts disabled",
             "permission denied", "access denied", "credentials")))
        result["git_remote"] = {key: remote[key] for key in ("returncode", "timed_out", "credentials_error")}
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--deep", action="store_true")
    parser.add_argument("--git-remote-check")
    parser.add_argument("--label", type=_label, default="manual")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    out_dir = args.out_dir or Path(os.environ.get("LOCALAPPDATA", Path.home())) / "RelayForge-POC" / "poc10"
    if args.dry_run:
        binaries = {name: name for name in ("claude", "codex", "agy")}
        print(redact(json.dumps(_commands(binaries, out_dir, args.deep, args.git_remote_check, args.label),
                                ensure_ascii=False, indent=2)))
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    result = run_probe(out_dir, args.deep, args.git_remote_check)
    started_at = datetime.now().astimezone()
    result["label"] = args.label
    result["pid"] = os.getpid()
    result["started_at"] = started_at.isoformat()
    result["boot_time"] = datetime.fromtimestamp(psutil.boot_time(), tz=timezone.utc).isoformat()
    payload = redact(json.dumps(result, ensure_ascii=False, indent=2))
    output_path = write_evidence(out_dir, args.label, payload, started_at.replace(tzinfo=None))
    statuses = ", ".join(f"{name}={data['auth']}" for name, data in result["agents"].items())
    print(f"POC-10: {statuses}; evidencia={output_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
