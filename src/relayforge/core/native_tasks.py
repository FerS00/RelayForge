from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from relayforge.adapters.base import ConversationContext
from relayforge.adapters.codex.chat import CodexChat
from relayforge.core.actions import ActionError, resource_path
from relayforge.core.ids import new_ulid


def tree_snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    directories = [root]
    while directories:
        directory = directories.pop()
        for path in directory.iterdir():
            relative = path.relative_to(root)
            if path.name in {".git", ".venv", "node_modules"}:
                continue
            resource_path(str(path), root)
            if path.is_dir():
                directories.append(path)
                if len(directories) + len(result) >= 10000:
                    raise ActionError("native_resource_too_large")
            elif path.is_file():
                if len(result) >= 10000 or path.stat().st_size > 8 * 1024 * 1024:
                    raise ActionError("native_resource_too_large")
                result[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def native_snapshot(root: Path) -> str:
    return hashlib.sha256(
        json.dumps({"tree": tree_snapshot(root), "head": git_head(root)}, sort_keys=True).encode()
    ).hexdigest()


def git_head(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


async def run_native(
    chat: CodexChat, root: Path, request: str, model: str, action_id: str, effort: str = ""
) -> dict[str, Any]:
    before = tree_snapshot(root)
    head_before = git_head(root)
    context = ConversationContext(action_id, new_ulid(), False, root, action_id, model, effort=effort)
    outcome, text, changes = "invalid_output", [], []
    async for event in chat.chat(
        context,
        "Realiza únicamente esta solicitud dentro del workspace: "
        + request
        + "\nNo borres archivos, no hagas commit ni operaciones remotas, no instales ni eleves permisos. "
        + "Si requiere desarrollo de software, detente: se debe ejecutar un Job con auditoría independiente.",
    ):
        if event.type == "agent.message":
            text.append(str(event.data["text"])[:100_000])
        elif event.type == "file.changed":
            changed = resource_path(str(event.data["path"]), root)
            if not changed.is_relative_to(root):
                raise ActionError("native_change_outside_workspace")
            changes.append(str(changed.relative_to(root)))
        elif event.type == "agent.exit":
            outcome = str(event.data["outcome"])
    after = tree_snapshot(root)
    head_after = git_head(root)
    if head_before != head_after:
        raise ActionError("unexpected_git_head_change")
    if set(before) - set(after):
        raise ActionError("unexpected_file_deletion")
    if outcome != "ok":
        raise ActionError("native_task_" + outcome)
    return {
        "response": "\n".join(text),
        "changed_paths": sorted(
            set(changes) | {name for name, digest in after.items() if before.get(name) != digest}
        ),
        "snapshot_before": hashlib.sha256(json.dumps(before, sort_keys=True).encode()).hexdigest(),
    }
