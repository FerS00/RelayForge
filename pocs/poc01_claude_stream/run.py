"""Runner de Claude stream-json. Sin --dry-run puede consumir cuota y red."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.binaries import locate  # noqa: E402
from common.evidence import Evidence  # noqa: E402
from common.procs import JobObject, spawn_in_job  # noqa: E402

PROMPTS = [
    "Responde en una frase qué hace el paquete calc. Recuerda la palabra clave AZUL-7.",
    "¿Cuál era la palabra clave? Responde solo la palabra.",
    "Propón un plan para manejar la división entre cero en calc.div",
]
FORBIDDEN = {"--dangerously-skip-permissions", "--dangerously-bypass-approvals-and-sandbox",
             "--dangerously-bypass-hook-trust", "-s", "danger-full-access", "--last", "--sandbox"}


def build_argv(binary: str, session: str, turn: int, verbose: bool, schema: str) -> list[str]:
    argv = [binary, "-p", "--output-format", "stream-json"]
    if verbose:
        argv.append("--verbose")
    if turn == 0:
        argv.extend(["--session-id", session])
    else:
        argv.extend(["--resume", session])
    if turn == 2:
        argv.extend(["--json-schema", schema])
    return argv


def read_events(path: Path) -> list[dict]:
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                events.append(item)
        except json.JSONDecodeError:
            continue
    return events


def wait_stream(process: subprocess.Popen, path: Path, timeout: float) -> tuple[int, float | None, float | None]:
    started = time.monotonic()
    offset = 0
    pending = b""
    first_line = None
    first_text = None
    while process.poll() is None:
        if time.monotonic() - started >= timeout:
            raise subprocess.TimeoutExpired(process.args, timeout)
        if path.exists():
            with path.open("rb") as stream:
                stream.seek(offset)
                pending += stream.read()
                offset = stream.tell()
            lines = pending.split(b"\n")
            pending = lines.pop()
            for raw_line in lines:
                if not raw_line.strip():
                    continue
                moment = time.monotonic() - started
                if first_line is None:
                    first_line = moment
                try:
                    event = json.loads(raw_line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue
                if first_text is None and _assistant_text(event):
                    first_text = moment
        time.sleep(0.025)
    returncode = process.wait()
    if path.exists():
        with path.open("rb") as stream:
            stream.seek(offset)
            pending += stream.read()
    for raw_line in pending.splitlines():
        if not raw_line.strip():
            continue
        moment = time.monotonic() - started
        first_line = moment if first_line is None else first_line
        try:
            event = json.loads(raw_line.decode("utf-8", errors="replace"))
            if first_text is None and _assistant_text(event):
                first_text = moment
        except json.JSONDecodeError:
            pass
    return returncode, first_line, first_text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose-flag", choices=("auto", "on", "off"), default="on")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)
    session = str(uuid.uuid4())
    binary = locate("claude")
    schema = Path(__file__).with_name("plan.schema.json").read_text(encoding="utf-8")
    verbose = args.verbose_flag == "on"
    commands = [build_argv(binary.path.as_posix() if binary.path else "claude", session, i, verbose, schema)
                for i in range(3)]
    if args.dry_run:
        print(json.dumps(commands, ensure_ascii=False, indent=2))
        return 0
    evidence = Evidence("poc01_claude_stream")
    evidence.record_versions()
    if binary.path is None:
        evidence.verdict("FAIL", [{"id": "C0", "description": "binario encontrado", "passed": False,
                                   "evidence": "claude no localizado"}])
        return 3
    if not args.repo.is_dir():
        evidence.verdict("FAIL", [{"id": "C0", "description": "repositorio existe", "passed": False,
                                   "evidence": "--repo no es un directorio"}])
        return 2
    outputs: list[list[dict]] = []
    timings: list[dict] = []
    for index, prompt in enumerate(PROMPTS):
        prompt_path = evidence.write_text(f"turn{index + 1}.prompt", prompt)
        cmd = commands[index]
        with JobObject() as job:
            process = spawn_in_job(cmd, job, args.repo.resolve(), evidence.dir / f"turn{index + 1}.ndjson",
                                   evidence.dir / f"turn{index + 1}.stderr", prompt_path)
            try:
                code, first_line_seconds, first_text_seconds = wait_stream(
                    process, evidence.dir / f"turn{index + 1}.ndjson", args.timeout
                )
            except subprocess.TimeoutExpired:
                job.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
                for name in (f"turn{index + 1}.ndjson", f"turn{index + 1}.stderr"):
                    raw_path = evidence.dir / name
                    evidence.write_text(name, raw_path.read_text(encoding="utf-8", errors="replace")
                                         if raw_path.exists() else "")
                evidence.verdict("FAIL", [{"id": "timeout", "description": f"turno {index + 1}",
                                           "passed": False, "evidence": "timeout"}])
                return 1
        out_path = evidence.dir / f"turn{index + 1}.ndjson"
        evidence.write_text(out_path.name, out_path.read_text(encoding="utf-8", errors="replace"))
        events = read_events(out_path)
        stderr_path = evidence.dir / f"turn{index + 1}.stderr"
        stderr = stderr_path.read_text(encoding="utf-8", errors="replace")
        evidence.write_text(stderr_path.name, stderr)
        outputs.append(events)
        timings.append({"first_line_seconds": first_line_seconds,
                        "first_assistant_text_seconds": first_text_seconds, "returncode": code})
        if index == 0 and code != 0 and args.verbose_flag == "auto" and "verbose" in stderr.lower():
            retry = build_argv(str(binary.path), session, index, True, schema)
            with JobObject() as job:
                process = spawn_in_job(retry, job, args.repo.resolve(), evidence.dir / "turn1-retry.ndjson",
                                       evidence.dir / "turn1-retry.stderr", prompt_path)
                try:
                    code, _, _ = wait_stream(process, evidence.dir / "turn1-retry.ndjson", args.timeout)
                except subprocess.TimeoutExpired:
                    job.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                    code = -1
            commands[index] = retry
            if code == 0:
                commands[index + 1:] = [
                    build_argv(str(binary.path), session, turn, True, schema)
                    for turn in range(index + 1, len(commands))
                ]
            retry_path = evidence.dir / "turn1-retry.ndjson"
            evidence.write_text(retry_path.name, retry_path.read_text(encoding="utf-8", errors="replace"))
            retry_stderr = evidence.dir / "turn1-retry.stderr"
            evidence.write_text(retry_stderr.name, retry_stderr.read_text(encoding="utf-8", errors="replace"))
            outputs[index] = read_events(retry_path)
            timings[index]["retry_verbose"] = True
        if code != 0:
            evidence.write_json("timings.json", timings)
            evidence.verdict("FAIL", [{"id": "C0", "description": "proceso terminó correctamente",
                                       "passed": False, "evidence": f"turno {index + 1}: código {code}"}])
            return 1
    init = next((event for event in outputs[0]
                 if event.get("type") == "system" and event.get("subtype") == "init"), {})
    summary = {}
    for key in ("tools", "mcp_servers", "slash_commands", "skills", "model"):
        value = init.get(key)
        if isinstance(value, list):
            summary[key] = [item.get("name", str(item)) if isinstance(item, dict) else str(item) for item in value]
        elif value is not None:
            summary[key] = value.get("name") if isinstance(value, dict) else value
    evidence.write_json("init_summary.json", summary)
    evidence.write_json("timings.json", timings)
    turn1 = outputs[0]
    nonfinal = [e for e in turn1 if e.get("type") not in {"result", "assistant_final", "final"}]
    answer2 = json.dumps(outputs[1], ensure_ascii=False)
    final = outputs[2][-1] if outputs[2] else {}
    valid_field = None
    from jsonschema import validate
    for key, raw in [("structured_output", final.get("structured_output")), ("result", final.get("result"))]:
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
            validate(value, json.loads(schema))
            valid_field = key
            break
        except Exception:
            pass
    if valid_field is None:
        text = _assistant_text(final)
        for candidate in re.findall(r"\{.*?\}", text, re.DOTALL):
            try:
                validate(json.loads(candidate), json.loads(schema))
                valid_field = "content"
                break
            except Exception:
                pass
    criteria = [
        {"id": "C1", "description": "dos eventos JSON antes del final en turno 1",
         "passed": len(nonfinal) >= 2, "evidence": f"{len(nonfinal)} eventos"},
        {"id": "C2", "description": "turno 2 conserva AZUL-7", "passed": "AZUL-7" in answer2,
         "evidence": "AZUL-7" if "AZUL-7" in answer2 else "ausente"},
        {"id": "C3", "description": "turno 3 valida esquema", "passed": valid_field is not None,
         "evidence": valid_field or "sin JSON válido"},
        {"id": "C4", "description": "skills o slash commands disponibles",
         "passed": True if summary.get("skills") or summary.get("slash_commands") else None,
         "evidence": json.dumps({k: summary.get(k) for k in ("skills", "slash_commands")})
         if summary.get("skills") or summary.get("slash_commands") else "ninguno anunciado; requiere revisión manual"},
    ]
    status = ("FAIL" if any(c["passed"] is False for c in criteria[:3]) else
              "PASS" if criteria[3]["passed"] is True else "MANUAL")
    evidence.verdict(status, criteria)
    return 0 if status != "FAIL" else 1


def _assistant_text(event: dict) -> str:
    chunks = []
    for content in event.get("message", {}).get("content", event.get("content", [])):
        if isinstance(content, dict) and content.get("type") == "text":
            chunks.append(str(content.get("text", "")))
    return "\n".join(chunks)


if __name__ == "__main__":
    raise SystemExit(main())
