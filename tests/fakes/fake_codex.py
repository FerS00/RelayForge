from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    args = sys.argv[1:]
    try:
        cwd = Path(args[args.index("-C") + 1]).resolve()
    except (ValueError, IndexError):
        return 2
    prompt = sys.stdin.read()
    schema = Path(args[args.index("--output-schema") + 1]) if "--output-schema" in args else None
    if schema is None and "Realiza únicamente esta solicitud" in prompt:
        if "-s" not in args or args[args.index("-s") + 1] != "workspace-write":
            return 4
        (cwd / "fake-native.txt").write_text("native fixture", encoding="utf-8")
        print(
            json.dumps(
                {"type": "item.completed", "item": {"type": "agent_message", "text": "Archivo local creado"}}
            ),
            flush=True,
        )
        print(json.dumps({"type": "turn.completed"}), flush=True)
        return 0
    if schema is None or schema.name == "chat.schema.json":
        if os.getenv("FAKE_CODEX_CHAT_SCENARIO") == "stall":
            time.sleep(30)
        if os.getenv("FAKE_CODEX_CHAT_SCENARIO") == "auth":
            print(
                json.dumps({"type": "turn.failed", "error": {"message": "authentication required"}}),
                flush=True,
            )
            return 1
        resumed = "resume" in args
        if resumed:
            if args[args.index("resume") + 1] != "fake-chat-thread" or "sandbox_mode='read-only'" not in args:
                return 5
        elif "-s" not in args or args[args.index("-s") + 1] != "read-only":
            return 4
        print(json.dumps({"type": "fixture.invocation", "argv": args}), flush=True)
        if "--image" in args and not Path(args[args.index("--image") + 1]).is_file():
            return 6
        print(json.dumps({"type": "thread.started", "thread_id": "fake-chat-thread"}), flush=True)
        print(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": json.dumps(
                            {
                                "response": "Evidencia recibida"
                                if "EVIDENCIA ADJUNTA" in prompt
                                else "Contexto conservado"
                                if resumed
                                else "Hola desde Codex",
                                "action": None,
                            }
                        )
                        if schema
                        else (
                            "Evidencia recibida"
                            if "EVIDENCIA ADJUNTA" in prompt
                            else "Contexto conservado"
                            if resumed
                            else "Hola desde Codex"
                        ),
                    },
                }
            ),
            flush=True,
        )
        print(json.dumps({"type": "turn.completed"}), flush=True)
        return 0
    if schema and schema.name in {"plan.schema.json", "triage.schema.json"}:
        if "-s" not in args or args[args.index("-s") + 1] != "read-only":
            return 4
        if schema.name == "plan.schema.json":
            value = {
                "objective": "Plan de relevo",
                "summary": "Planificación Codex sin escrituras.",
                "steps": ["Implementar en el worktree existente"],
                "risks": [],
                "suggested_workflow": "feature",
            }
        else:
            payload = json.loads(prompt.split("\n", 1)[1])
            value = {
                "decisions": [
                    {"finding_id": item["id"], "decision": "accept", "reason": "Corrección requerida"}
                    for item in payload["findings"]
                ]
            }
        print(json.dumps({"type": "fixture.invocation", "argv": args}), flush=True)
        print(json.dumps({"type": "thread.started", "thread_id": "fake-plan-thread"}), flush=True)
        print(
            json.dumps(
                {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(value)}}
            ),
            flush=True,
        )
        print(
            json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}),
            flush=True,
        )
        return 0
    if (
        not any(marker in prompt for marker in ("Implementa la solicitud", "Corrige únicamente"))
        or not cwd.is_dir()
    ):
        return 3
    scenario = os.getenv("FAKE_CODEX_SCENARIO", "success")
    if scenario not in {"success", "outside", "parallel"}:
        print(json.dumps({"type": "turn.failed"}), flush=True)
        return 1
    relative_path = os.getenv("FAKE_CODEX_CHANGED_PATH", "fake-implementation.txt")
    changed = cwd.parent.parent / "outside.txt" if scenario == "outside" else cwd / relative_path
    overlap = False
    if scenario == "success":
        changed.parent.mkdir(parents=True, exist_ok=True)
        changed.write_text("generated by fake codex\n", encoding="utf-8", newline="\n")
    elif scenario == "parallel":
        marker = cwd.parent / f".active-{cwd.name}"
        marker.write_text("active", encoding="utf-8")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            active = [
                candidate
                for candidate in cwd.parent.glob(".active-*")
                if time.time() - candidate.stat().st_mtime < 2
            ]
            overlap = len(active) > 1
            if overlap:
                break
            time.sleep(0.05)
        changed.write_text("parallel fake implementation\n", encoding="utf-8", newline="\n")
    print(json.dumps({"type": "thread.started", "thread_id": "fake-thread-001"}), flush=True)
    print(
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "file_change",
                    "changes": [
                        {"path": str(changed), "kind": "add"},
                    ],
                },
            }
        ),
        flush=True,
    )
    print(
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": json.dumps(
                        {
                            "summary": (
                                "concurrent"
                                if overlap
                                else "Fake revision complete"
                                if "Corrige únicamente" in prompt
                                else "Fake implementation complete"
                            ),
                            "completed": True,
                        }
                    ),
                },
            }
        ),
        flush=True,
    )
    print(json.dumps({"type": "turn.completed"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
