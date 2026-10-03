"""Runner de eventos Codex; la ejecución real puede consumir cuota y red."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.binaries import locate  # noqa: E402
from common.evidence import Evidence  # noqa: E402
from common.procs import JobObject, spawn_in_job  # noqa: E402


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, timeout=30, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    return result.stdout.decode("utf-8", errors="replace").strip()


def require_sandbox(repo: Path) -> None:
    if not (repo / ".relayforge-sandbox").is_file():
        raise ValueError("--repo debe contener .relayforge-sandbox; se rechaza operar sobre otro repositorio")


def event_data(path: Path) -> tuple[list[dict], dict]:
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
            if isinstance(value, dict):
                events.append(value)
        except json.JSONDecodeError:
            continue
    types = Counter(event.get("type", "unknown") for event in events)
    item_types = Counter(item.get("item", {}).get("type", "unknown") for item in events
                         if isinstance(item.get("item"), dict))
    return events, {"type": dict(types), "item.type": dict(item_types)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model")
    parser.add_argument("--effort", default="high")
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    runtime = Path(os.environ.get("RELAYFORGE_POC_RUNTIME", r"C:\RF\poc"))
    worktree = runtime / f"poc02-wt-{stamp}"
    branch = f"poc/poc02-{stamp}"
    binary = locate("codex")
    schema = Path(__file__).with_name("summary.schema.json").resolve()
    first = [str(binary.path) if binary.path else "codex", "exec", "--json", "-C", str(worktree),
             "-s", "workspace-write", "-c", "windows.sandbox='unelevated'", "-c",
             f'model_reasoning_effort="{args.effort}"', "--output-schema", str(schema), "-o", "last.md"]
    resume = [str(binary.path) if binary.path else "codex", "exec", "resume", "<thread_id>",
              "-c", 'sandbox_mode="workspace-write"', "-c", "windows.sandbox='unelevated'", "-c",
              f'model_reasoning_effort="{args.effort}"', "--json"]
    if args.model:
        first.extend(["-m", args.model])
        resume.extend(["-m", args.model])
    first.append("-")
    resume.append("-")
    if args.dry_run:
        print(json.dumps([first, resume], ensure_ascii=False, indent=2))
        return 0
    evidence = Evidence("poc02_codex_events")
    evidence.record_versions()
    try:
        require_sandbox(args.repo)
    except ValueError as exc:
        evidence.verdict("FAIL", [{"id": "C0", "description": "repositorio sandbox", "passed": False,
                                   "evidence": str(exc)}])
        print(str(exc), file=sys.stderr)
        return 2
    if binary.path is None:
        evidence.verdict("FAIL", [{"id": "C0", "description": "binario encontrado", "passed": False,
                                   "evidence": "codex no localizado"}])
        return 3
    before = git(args.repo, "status", "--porcelain")
    runtime.mkdir(parents=True, exist_ok=True)
    git(args.repo, "worktree", "add", "-b", branch, str(worktree), "HEAD")
    prompt = ("Implementa tú directamente. No delegues en Claude, no uses claude-delegate ni Claude Companion.\n"
              "Haz que calc.div lance ZeroDivisionError con mensaje claro y añade un test. No hagas commit.\n")
    evidence.write_text("brief.txt", prompt)
    output = evidence.dir / "events.ndjson"
    try:
        with JobObject() as job:
            proc = spawn_in_job(first, job, worktree, output, evidence.dir / "stderr.txt",
                                evidence.write_text("turn1.prompt", prompt))
            try:
                proc.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                job.terminate()
                proc.wait(timeout=5)
                for name in ("events.ndjson", "stderr.txt"):
                    raw_path = evidence.dir / name
                    evidence.write_text(name, raw_path.read_text(encoding="utf-8", errors="replace")
                                         if raw_path.exists() else "")
                evidence.verdict("FAIL", [{"id": "timeout", "description": "codex exec", "passed": False,
                                           "evidence": "timeout"}])
                return 1
        evidence.write_text(output.name, output.read_text(encoding="utf-8", errors="replace"))
        stderr_path = evidence.dir / "stderr.txt"
        evidence.write_text(stderr_path.name, stderr_path.read_text(encoding="utf-8", errors="replace"))
        events, histogram = event_data(output)
        evidence.write_json("event_histogram.json", histogram)
        thread_id = next((e.get("thread_id") for e in events if e.get("type") == "thread.started"), None)
        changes = [e.get("item", {}).get("changes", []) for e in events if e.get("item", {}).get("type") == "file_change"]
        changed_paths = sorted({str(change.get("path")) for group in changes for change in group
                                if isinstance(change, dict) and change.get("path")})
        commands = [{"command": e.get("item", {}).get("command"),
                     "exit_code": e.get("item", {}).get("exit_code")} for e in events
                    if e.get("item", {}).get("type") == "command_execution"]
        evidence.write_json("events_summary.json", {"thread_id": thread_id, "file_change": changed_paths,
                                                     "command_execution": commands})
        git(worktree, "add", "-N", ".")
        diff = git(worktree, "diff")
        evidence.write_text("changes.diff", diff)
        diff_paths = set(filter(None, git(worktree, "diff", "--name-only").splitlines()))
        final = next((e.get("item", {}).get("text", "") for e in reversed(events)
                      if e.get("type") == "item.completed" and e.get("item", {}).get("type") == "agent_message"), "")
        last_md = worktree / "last.md"
        if last_md.exists():
            evidence.write_text("last.md", last_md.read_text(encoding="utf-8", errors="replace"))
        criteria = [
            {"id": "C1", "description": "thread.started y turn.completed", "passed":
             any(e.get("type") == "thread.started" for e in events) and any(e.get("type") == "turn.completed" for e in events),
             "evidence": f"thread_id={thread_id}; events={histogram['type']}"},
            {"id": "C2", "description": "file_change incluido en diff", "passed": bool(changed_paths) and set(changed_paths) <= diff_paths,
             "evidence": ", ".join(changed_paths) or "derivar del diff"},
            {"id": "C3", "description": "salida final conforme al esquema", "passed": _valid_summary(last_md, final, schema),
             "evidence": "last.md o mensaje final"},
        ]
        if not thread_id:
            evidence.verdict("FAIL", [{"id": "C0", "description": "thread_id disponible", "passed": False,
                                       "evidence": "Codex no devolvió thread.started"}])
            return 1
        resume[3] = thread_id
        second_prompt = "Añade un docstring a div. No hagas commit.\n"
        with JobObject() as job:
            proc = spawn_in_job(resume, job, worktree, evidence.dir / "resume.ndjson",
                                evidence.dir / "resume.stderr", evidence.write_text("turn2.prompt", second_prompt))
            try:
                proc.wait(timeout=args.timeout)
            except subprocess.TimeoutExpired:
                job.terminate()
                proc.wait(timeout=5)
                criteria.append({"id": "C4", "description": "resume agrega docstring", "passed": False,
                                 "evidence": "timeout"})
            else:
                git(worktree, "add", "-N", ".")
                diff_after = git(worktree, "diff")
                evidence.write_text("changes.diff", diff_after)
                criteria.append({"id": "C4", "description": "resume agrega docstring",
                                 "passed": '"""' in diff_after or "'''" in diff_after,
                                 "evidence": "docstring en diff" if '"""' in diff_after else "no detectado"})
        resume_output = evidence.dir / "resume.ndjson"
        evidence.write_text(resume_output.name, resume_output.read_text(encoding="utf-8", errors="replace"))
        resume_stderr = evidence.dir / "resume.stderr"
        evidence.write_text(resume_stderr.name, resume_stderr.read_text(encoding="utf-8", errors="replace"))
        after = git(args.repo, "status", "--porcelain")
        criteria.append({"id": "C5", "description": "repositorio principal sin cambios nuevos",
                         "passed": before == after, "evidence": "status previo y posterior comparados"})
        passed = all(c["passed"] for c in criteria)
        evidence.verdict("PASS" if passed else "FAIL", criteria)
        print(worktree)
        return 0 if passed else 1
    except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
        evidence.verdict("FAIL", [{"id": "C0", "description": "ejecución", "passed": False, "evidence": str(exc)}])
        print(str(exc), file=sys.stderr)
        return 1


def _valid_summary(path: Path, message: str, schema: Path) -> bool:
    from jsonschema import validate

    candidates = [path.read_text(encoding="utf-8", errors="replace")] if path.is_file() else []
    candidates.append(message)
    for text in candidates:
        try:
            validate(json.loads(text), json.loads(schema.read_text(encoding="utf-8")))
            return True
        except Exception:
            continue
    return False


if __name__ == "__main__":
    raise SystemExit(main())
