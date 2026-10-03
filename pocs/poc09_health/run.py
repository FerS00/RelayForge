"""Recopila señales de instalación, versión, autenticación y rate limit."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.binaries import locate  # noqa: E402
from common.evidence import Evidence  # noqa: E402
from common.procs import JobObject, spawn_in_job  # noqa: E402
from common.redact import redact  # noqa: E402

CLAUDE_AUTH_FIELDS = ("loggedIn", "authMethod", "apiProvider", "subscriptionType")


def _json_object(output: str) -> dict | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(output):
        if char == "{":
            try:
                value, _ = decoder.raw_decode(output[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    return None


def claude_auth_result(returncode: int, output: str) -> tuple[str, dict]:
    del returncode
    data = _json_object(output)
    if data is None or not isinstance(data.get("loggedIn"), bool):
        return "UNKNOWN", {}
    evidence = {key: data[key] for key in CLAUDE_AUTH_FIELDS if key in data and
                isinstance(data[key], (str, bool, int, type(None)))}
    return ("AVAILABLE" if data["loggedIn"] else "AUTH_REQUIRED"), evidence


def codex_auth_result(returncode: int, output: str) -> tuple[str, str]:
    first_line = redact(output.splitlines()[0].strip()) if output.splitlines() else ""
    normalized = first_line.casefold()
    if returncode == 1 or normalized.startswith("not logged in"):
        return "AUTH_REQUIRED", first_line
    if returncode == 0 and normalized.startswith("logged in"):
        return "AVAILABLE", first_line
    return "UNKNOWN", first_line


def agy_probe_result(output: str) -> tuple[str, dict]:
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        result = event.get("result") if isinstance(event, dict) and event.get("event") == "result" else None
        if isinstance(result, dict):
            status = result.get("status")
            response = result.get("response")
            nonempty = isinstance(response, str) and bool(response.strip())
            evidence = {"event": "result", "status": status, "response_nonempty": nonempty}
            if status == "SUCCESS" and nonempty:
                return "AVAILABLE", evidence
            return "UNKNOWN", evidence
    return "UNKNOWN", {"event": None, "status": None, "response_nonempty": False}


def commands_for(agent: str, binary: str) -> list[list[str]]:
    if agent == "claude":
        return [[binary, "--version"], [binary, "auth", "status"], [binary, "auth", "status", "--json"],
                [binary, "doctor"]]
    if agent == "codex":
        return [[binary, "--version"], [binary, "login", "status"], [binary, "doctor"]]
    return [[binary, "--version"], [binary, "--help"]]


def _run(command: list[str], timeout: float, env: dict[str, str] | None = None) -> dict:
    with TemporaryDirectory(prefix="relayforge-health-") as temporary:
        root = Path(temporary)
        stdout_path, stderr_path = root / "stdout.txt", root / "stderr.txt"
        try:
            job = JobObject()
            try:
                process = spawn_in_job(command, job, Path.cwd(), stdout_path, stderr_path, env=env)
                try:
                    code = process.wait(timeout=timeout)
                    timed_out = False
                except subprocess.TimeoutExpired:
                    job.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    code, timed_out = None, True
            finally:
                job.close()
            stdout = stdout_path.read_text(encoding="utf-8", errors="replace") if stdout_path.exists() else ""
            stderr = stderr_path.read_text(encoding="utf-8", errors="replace") if stderr_path.exists() else ""
            return {"returncode": code, "output": redact(stdout + stderr), "timed_out": timed_out}
        except (OSError, NotImplementedError) as exc:
            return {"returncode": None, "output": redact(str(exc)), "timed_out": False}


def _walk_rates(value: object, found: list[dict], agent: str, parent: str = "") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            if key_text.lower() in {"type", "event"} and isinstance(child, str) and re.search(
                    r"rate|limit", child, re.IGNORECASE):
                numbers = re.findall(r"\d+(?:\.\d+)?", json.dumps(value, ensure_ascii=False))
                found.append({"agent": agent, "key": f"{parent}.{key_text}={child}".strip("."),
                              "numeric_example": numbers[:8]})
            if "rate" in key_text.lower() or "limit" in key_text.lower():
                numbers = re.findall(r"\d+(?:\.\d+)?", json.dumps(child, ensure_ascii=False))
                found.append({"agent": agent, "key": f"{parent}.{key_text}".strip("."),
                              "numeric_example": numbers[:8]})
            _walk_rates(child, found, agent, f"{parent}.{key_text}".strip("."))
    elif isinstance(value, list):
        for item in value:
            _walk_rates(item, found, agent, parent)


def _rate_signals(results_root: Path) -> list[dict]:
    signals: list[dict] = []
    for folder in ("poc01*", "poc02*", "poc03*"):
        for poc_dir in results_root.glob(folder):
            paths = {path for pattern in ("*.json", "*.jsonl", "*.ndjson")
                     for path in poc_dir.rglob(pattern)}
            for path in paths:
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                try:
                    parsed = [json.loads(content)]
                except json.JSONDecodeError:
                    parsed = []
                    for line in content.splitlines():
                        try:
                            parsed.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
                for value in parsed:
                    _walk_rates(value, signals, "claude" if "poc01" in folder else
                                "codex" if "poc02" in folder else "agy")
    dedup: dict[tuple[str, str], dict] = {}
    for item in signals:
        dedup.setdefault((item["agent"], item["key"]), item)
    return list(dedup.values())


def _rmtree(path: Path) -> None:
    if path.exists():
        import shutil
        shutil.rmtree(path, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--with-auth-simulation", action="store_true")
    parser.add_argument("--deep", action="store_true")
    args = parser.parse_args(argv)
    commands = {agent: commands_for(agent, agent if args.dry_run else
                                    str(locate(agent).path) if locate(agent).path else agent)
                for agent in ("claude", "codex", "agy")}
    if args.with_auth_simulation:
        commands["simulation"] = {"claude": ["claude", "auth", "status"],
                                  "codex": ["codex", "login", "status"], "agy": "not_supported"}
    if args.deep:
        commands["deep_probe"] = ["agy", "-p", "<prompt>", "--output-format", "stream-json",
                                  "--print-timeout", "60s"]
    if args.dry_run:
        print(redact(json.dumps(commands, ensure_ascii=False, indent=2)))
        return 0

    evidence = Evidence("poc09_health")
    evidence.record_versions()
    health: dict[str, dict] = {}
    command_log: dict[str, list[dict]] = {}
    sim_dirs: list[Path] = []
    try:
        for agent in ("claude", "codex", "agy"):
            found = locate(agent)
            binary = str(found.path) if found.path else agent
            rows = []
            version_info = _run([binary, "--version"], 60) if found.path else {
                "returncode": None, "output": "missing", "timed_out": False}
            rows.append({"name": "version", **version_info})
            auth_commands = commands_for(agent, binary)[1:-1] if agent == "claude" else (
                [[binary, "login", "status"]] if agent == "codex" else [[binary, "--help"]])
            auth_results = [_run(command, 60) for command in auth_commands] if found.path else []
            for command, result in zip(auth_commands, auth_results):
                rows.append({"name": "auth", "command": agent, "args": command[1:], **result})
            doctor_result = None
            if agent in {"claude", "codex"} and found.path:
                doctor_result = _run([binary, "doctor"], 90)
                rows.append({"name": "doctor", **doctor_result})
            with TemporaryDirectory(prefix="not-installed-") as empty:
                miss = locate(agent, env={"PATH": empty, "LOCALAPPDATA": empty})
                not_installed = "missing" if miss.path is None else "found"
            if agent == "claude" and found.path:
                auth, auth_evidence = "UNKNOWN", {}
                for auth_result in auth_results:
                    auth, auth_evidence = claude_auth_result(
                        auth_result["returncode"] if auth_result["returncode"] is not None else -1,
                        auth_result["output"])
                    if auth != "UNKNOWN":
                        break
            elif agent == "codex" and found.path:
                primary_auth = auth_results[0] if auth_results else {"returncode": None, "output": ""}
                auth, auth_evidence = codex_auth_result(
                    primary_auth["returncode"] if primary_auth["returncode"] is not None else -1,
                    primary_auth["output"])
            else:
                auth = "UNKNOWN"
                auth_evidence = {} if agent == "claude" else "" if agent == "codex" else {
                    "status": "UNKNOWN"}
            health[agent] = {"installed": found.path is not None,
                "version": version_info["output"].splitlines()[0] if version_info["output"] else None,
                "auth": auth, "auth_evidence": auth_evidence,
                "doctor": "n/a" if doctor_result is None else
                    "timeout" if doctor_result["timed_out"] else
                    ("warn" if re.search(r"warning", doctor_result["output"], re.IGNORECASE) else "ok")
                    if doctor_result["returncode"] == 0 else "fail",
                "simulated_auth_required_signal": None, "not_installed_simulation": not_installed}
            command_log[agent] = rows

        if args.with_auth_simulation:
            for agent, env_key, command in (
                ("claude", "CLAUDE_CONFIG_DIR", ["auth", "status"]),
                ("codex", "CODEX_HOME", ["login", "status"])):
                found = locate(agent)
                if found.path:
                    temp_dir = evidence.dir / f"simulation-{agent}"
                    temp_dir.mkdir()
                    sim_dirs.append(temp_dir)
                    env = os.environ.copy()
                    env[env_key] = str(temp_dir)
                    result = _run([str(found.path), *command], 60, env)
                    simulator = claude_auth_result if agent == "claude" else codex_auth_result
                    signal, _ = simulator(result["returncode"] if result["returncode"] is not None else -1,
                                          result["output"])
                    health[agent]["simulated_auth_required_signal"] = signal
                    command_log[agent].append({"name": "auth-simulation", **result,
                                               "first_40_lines": result["output"].splitlines()[:40]})
            health["agy"]["simulated_auth_required_signal"] = "not_supported"
            command_log["agy"].append({"name": "auth-simulation", "status": "not_supported"})

        if args.deep and locate("agy").path:
            agy_binary = str(locate("agy").path)
            prompt = "Responde solo OK. No ejecutes comandos."
            result = _run([agy_binary, "-p", prompt, "--output-format", "stream-json",
                           "--print-timeout", "60s"], 60)
            health["agy"]["auth"], health["agy"]["auth_evidence"] = agy_probe_result(result["output"])
            command_log["agy"].append({"name": "deep-auth-probe", "command": "agy",
                                       "args": ["-p", "<prompt>", "--output-format", "stream-json",
                                                "--print-timeout", "60s"], **result})
        rates = _rate_signals(Path(__file__).resolve().parents[1] / "results")
        evidence.write_json("rate_signals.json", {"signals": rates})
        evidence.write_json("command_results.json", command_log)
        evidence.write_json("health.json", health)
        criteria = [
            {"id": "C1", "passed": all(health[name]["installed"] and health[name]["version"]
                                          for name in ("claude", "codex", "agy"))},
            {"id": "C2", "passed": all(health[name]["auth"] == "AVAILABLE" and health[name]["auth_evidence"]
                                          for name in ("claude", "codex"))},
            {"id": "C3", "passed": all(health[name]["not_installed_simulation"] == "missing"
                                          for name in ("claude", "codex", "agy"))},
            {"id": "C4", "passed": (all(health[name]["simulated_auth_required_signal"] == "AUTH_REQUIRED"
                                          for name in ("claude", "codex")) if args.with_auth_simulation else None)},
            {"id": "C5", "passed": any(signal["agent"] == "claude" for signal in rates)},
        ]
        status = "FAIL" if any(item["passed"] is False for item in criteria) else (
            "MANUAL" if any(item["passed"] is None for item in criteria) else "PASS")
        evidence.verdict(status, criteria)
        return 0 if status != "FAIL" else 1
    finally:
        for path in sim_dirs:
            _rmtree(path)


if __name__ == "__main__":
    raise SystemExit(main())
