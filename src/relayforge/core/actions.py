from __future__ import annotations

import asyncio
import hashlib
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from relayforge.core.conversation_settings import load_tools, tool_disabled
from relayforge.core.ids import new_ulid
from relayforge.db.models import ChatAction, ChatTurn, Conversation, utc_now
from relayforge.security.redact import redact_text


class ActionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal[
        "list_directory",
        "read_file",
        "write_file",
        "native_task",
        "development_job",
        "start_preview",
        "stop_preview",
        "desktop_launch",
        "desktop_inspect",
        "desktop_invoke",
        "desktop_set_value",
        "desktop_type",
        "desktop_keys",
        "desktop_menu",
        "desktop_capture",
        "desktop_close",
    ]
    path: str = Field(default="", max_length=2048)
    content: str = Field(default="", max_length=100_000)
    request: str = Field(default="", max_length=100_000)
    repository_id: str = Field(default="", max_length=128)


class ChatReply(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    response: str = Field(max_length=100_000)
    action: ActionProposal | None


class ActionError(ValueError):
    pass


def resource_path(raw: str, workspace: Path) -> Path:
    if not raw or "\x00" in raw or raw.startswith(("\\\\", "//")):
        raise ActionError("resource_path_invalid")
    candidate = Path(raw)
    if candidate.drive and not candidate.is_absolute():
        raise ActionError("resource_path_invalid")
    if ":" in candidate.name:
        raise ActionError("resource_path_invalid")
    if candidate.stem.upper() in {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *("COM" + str(i) for i in range(10)),
        *("LPT" + str(i) for i in range(10)),
    }:
        raise ActionError("resource_path_invalid")
    candidate = candidate if candidate.is_absolute() else workspace / candidate
    # Reject reparse/symlink traversal before resolving, including junctions.
    for part in (candidate, *candidate.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ActionError("resource_link_rejected")
    result = candidate.resolve()
    protected = {".git", ".ssh", ".codex", ".claude", ".gemini", "windows", "program files", "programdata"}
    if any(part.casefold() in protected for part in result.parts) or result.name.casefold().startswith(
        ".env"
    ):
        raise ActionError("resource_protected")
    if result.suffix.casefold() in {".pem", ".key", ".pfx"} or result.name.casefold() in {
        "auth.json",
        "credentials.json",
    }:
        raise ActionError("resource_protected")
    return result


def snapshot(path: Path, allow_missing_parents: bool = False) -> str:
    if not path.exists():
        if not path.parent.is_dir():
            if not allow_missing_parents:
                raise ActionError("resource_parent_missing")
            # New files may create intermediate folders; bind to the nearest existing ancestor.
            ancestor = next(parent for parent in path.parents if parent.is_dir())
            return f"absent:{path.relative_to(ancestor).as_posix()}:{ancestor.stat().st_mtime_ns}"
        return "absent:" + str(path.parent.stat().st_mtime_ns)
    if path.is_file():
        if path.stat().st_size > 1024 * 1024:
            raise ActionError("resource_too_large")
        return "file:" + hashlib.sha256(path.read_bytes()).hexdigest()
    if path.is_dir():
        entries = sorted((p.name, p.stat(follow_symlinks=False).st_mtime_ns) for p in path.iterdir())
        if len(entries) > 2000:
            raise ActionError("resource_too_large")
        return "dir:" + hashlib.sha256(json.dumps(entries).encode()).hexdigest()
    raise ActionError("resource_kind_invalid")


class ActionService:
    def __init__(self, sessions: sessionmaker[Session], previews: Any = None, desktop: Any = None) -> None:
        self.sessions = sessions
        self.previews = previews
        self.desktop = desktop
        self.locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def serialize(row: ChatAction) -> dict[str, Any]:
        return {
            "id": row.id,
            "turn_id": row.turn_id,
            "kind": row.kind,
            "payload": {
                **json.loads(row.payload_json),
                "path": row.resource_path or json.loads(row.payload_json).get("path", ""),
            },
            "operation_hash": row.operation_hash,
            "status": row.status,
            "version": row.version,
            "result": json.loads(row.result_json) if row.result_json else None,
        }

    def list(self, conversation_id: str) -> list[dict[str, Any]]:
        with self.sessions() as session:
            return [
                self.serialize(row)
                for row in session.scalars(
                    select(ChatAction)
                    .where(ChatAction.conversation_id == conversation_id)
                    .order_by(ChatAction.id)
                )
            ]

    def propose(self, turn_id: str, proposal: ActionProposal) -> tuple[dict[str, Any], bool]:
        payload = proposal.model_dump()
        if any(redact_text(payload[key]) != payload[key] for key in ("content", "request")):
            raise ActionError("action_sensitive_payload")
        with self.sessions.begin() as session:
            turn = session.get(ChatTurn, turn_id)
            if turn is None:
                raise ActionError("turn_not_found")
            disabled = tool_disabled(load_tools(turn.tools_json), proposal.kind)
            if disabled is not None:
                # Enforced in core: the rejection is persisted and returned to the agent.
                encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
                rejected = ChatAction(
                    id=new_ulid(),
                    conversation_id=turn.conversation_id,
                    turn_id=turn.id,
                    kind=proposal.kind,
                    payload_json=encoded,
                    resource_path="",
                    snapshot="tool-disabled",
                    operation_hash=hashlib.sha256((encoded + "tool-disabled").encode()).hexdigest(),
                    status="rejected",
                    version=0,
                    result_json=json.dumps({"error": "tool_disabled:" + disabled}),
                    finished_at=utc_now(),
                )
                session.add(rejected)
                session.flush()
                return self.serialize(rejected), False
            conversation = session.get(Conversation, turn.conversation_id)
            assert conversation is not None
            workspace = Path(conversation.workspace_dir).resolve()
            immediate = False
            controlled_path = ""
            if proposal.kind.startswith("desktop_"):
                resource_snapshot, immediate = self._desktop_proposal(turn.conversation_id, proposal)
            elif proposal.kind in {"start_preview", "stop_preview"}:
                if self.previews is None:
                    raise ActionError("preview_unavailable")
                if self.previews.settings.container_mode:
                    raise ActionError("preview_unavailable")
                if proposal.kind == "start_preview" and not self.previews.gateway_available:
                    raise ActionError(self.previews.gateway_error or "preview_gateway_unavailable")
                if proposal.kind == "start_preview":
                    root_ref = proposal.repository_id or "workspace"
                    try:
                        resource_snapshot, command_preview = self.previews.snapshot(
                            session, turn.conversation_id, root_ref, proposal.path
                        )
                    except ValueError as exc:
                        raise ActionError(str(exc)) from None
                    immediate = not command_preview
                else:
                    if not proposal.request:
                        raise ActionError("preview_id_required")
                    preview = self.previews.gateway_preview(proposal.request)
                    if preview is None or preview["conversation_id"] != turn.conversation_id:
                        raise ActionError("preview_not_found")
                    resource_snapshot = "preview-stop:" + proposal.request
                    immediate = True
            elif proposal.kind == "development_job":
                if not proposal.repository_id or not proposal.request:
                    raise ActionError("development_requires_repository_and_request")
                from relayforge.db.models import Repository

                repository = session.get(Repository, proposal.repository_id)
                if repository is None or not repository.enabled:
                    raise ActionError("repository_not_found")
                resource_snapshot = repository.path + ":" + repository.check_commands_json
                # The Job itself requests precise plan approval before changes.
                immediate = True
            else:
                path = resource_path(proposal.path, workspace)
                from relayforge.db.models import Job

                for job in session.scalars(
                    select(Job).where(
                        Job.worktree_path.is_not(None),
                        Job.status.not_in(["COMPLETED", "FAILED", "CANCELLED"]),
                    )
                ):
                    root = Path(job.worktree_path or "").resolve()
                    if path.is_relative_to(root) or root.is_relative_to(path):
                        raise ActionError("resource_job_active")
                controlled_path = str(path)
                if proposal.kind == "native_task" and (not path.is_dir() or not proposal.request):
                    raise ActionError("native_task_requires_directory_and_request")
                if proposal.kind == "native_task":
                    from relayforge.core.native_tasks import native_snapshot

                    resource_snapshot = "native:" + native_snapshot(path)
                else:
                    resource_snapshot = snapshot(path, proposal.kind == "write_file")
                immediate = proposal.kind in {"read_file", "list_directory"} and path.is_relative_to(
                    workspace
                )
            encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
            row = ChatAction(
                id=new_ulid(),
                conversation_id=turn.conversation_id,
                turn_id=turn.id,
                kind=proposal.kind,
                payload_json=encoded,
                resource_path=controlled_path,
                snapshot=resource_snapshot,
                operation_hash=hashlib.sha256((encoded + resource_snapshot).encode()).hexdigest(),
                status="approved" if immediate else "pending",
                version=0,
            )
            session.add(row)
            session.flush()
            return self.serialize(row), immediate

    def decide(
        self, conversation_id: str, action_id: str, version: int, operation_hash: str, decision: str, key: str
    ) -> dict[str, Any]:
        with self.sessions.begin() as session:
            row = session.get(ChatAction, action_id)
            if row is None or row.conversation_id != conversation_id:
                raise ActionError("action_not_found")
            if row.decision_key == key:
                if row.operation_hash != operation_hash or (row.status == "rejected") != (
                    decision == "reject"
                ):
                    raise ActionError("decision_replay_mismatch")
                return {**self.serialize(row), "replay": True}
            if row.version != version or row.operation_hash != operation_hash or row.status != "pending":
                raise ActionError("action_version_conflict")
            if decision not in {"approve", "reject"}:
                raise ActionError("decision_invalid")
            if decision == "approve":
                self.validate_policy(session, row)
            self.validate_snapshot(row)
            row.decision_key, row.status = key, "approved" if decision == "approve" else "rejected"
            row.version += 1
            return self.serialize(row)

    @staticmethod
    def validate_policy(session: Session, row: ChatAction) -> None:
        turn = session.get(ChatTurn, row.turn_id)
        disabled = tool_disabled(load_tools(turn.tools_json if turn else None), row.kind)
        if disabled is not None:
            raise ActionError("tool_disabled:" + disabled)

    def _desktop_proposal(self, conversation_id: str, proposal: ActionProposal) -> tuple[str, bool]:
        from relayforge.desktop.policy import DesktopPolicyError, parse_request, requires_path_approval
        from relayforge.desktop.service import DesktopError

        if self.desktop is None or not self.desktop.available:
            raise ActionError("desktop_unavailable")
        try:
            if proposal.kind == "desktop_launch":
                # Launching an application always needs an exact approval.
                return self.desktop.app_snapshot(proposal.path), False
            request = parse_request(proposal.kind, proposal.request)
            snapshot_value = self.desktop.target_snapshot(conversation_id, proposal.path)
            approval = requires_path_approval(proposal.kind, request, self.desktop.allowed_dirs())
        except (DesktopPolicyError, DesktopError) as exc:
            raise ActionError(exc.code) from None
        return snapshot_value, not approval

    def validate_snapshot(self, row: ChatAction) -> None:
        if row.kind.startswith("desktop_"):
            from relayforge.desktop.service import DesktopError

            payload = json.loads(row.payload_json)
            if self.desktop is None:
                raise ActionError("desktop_unavailable")
            try:
                current = (
                    self.desktop.app_snapshot(payload["path"])
                    if row.kind == "desktop_launch"
                    else self.desktop.target_snapshot(row.conversation_id, payload["path"])
                )
            except DesktopError as exc:
                raise ActionError(exc.code) from None
            if current != row.snapshot:
                raise ActionError("resource_snapshot_changed")
        elif row.kind == "start_preview":
            if self.previews is None:
                raise ActionError("preview_unavailable")
            payload = json.loads(row.payload_json)
            root_ref = payload.get("repository_id") or "workspace"
            try:
                current_snapshot, _ = self.previews.snapshot_for_action(
                    row.conversation_id, root_ref, payload.get("path", "")
                )
            except ValueError as exc:
                raise ActionError(str(exc)) from None
            if current_snapshot != row.snapshot:
                raise ActionError("resource_snapshot_changed")
        elif row.kind == "stop_preview":
            return
        elif row.kind == "development_job":
            from relayforge.db.models import Repository

            with self.sessions() as session:
                payload = json.loads(row.payload_json)
                repository = session.get(Repository, payload["repository_id"])
                if (
                    repository is None
                    or not repository.enabled
                    or repository.path + ":" + repository.check_commands_json != row.snapshot
                ):
                    raise ActionError("repository_snapshot_changed")
        else:
            path = resource_path(row.resource_path, Path(row.resource_path).parent)
            if row.kind == "native_task":
                from relayforge.core.native_tasks import native_snapshot

                current_snapshot = "native:" + native_snapshot(path)
            else:
                current_snapshot = snapshot(path, row.kind == "write_file")
            if current_snapshot != row.snapshot:
                raise ActionError("resource_snapshot_changed")

    async def execute(
        self, action_id: str, executor: Callable[[str, str, dict[str, Any]], Awaitable[dict[str, Any]]]
    ) -> dict[str, Any]:
        with self.sessions() as session:
            row = session.get(ChatAction, action_id)
            if row is None:
                raise ActionError("action_not_found")
            payload = json.loads(row.payload_json)
            if row.resource_path:
                payload["path"] = row.resource_path
            kind = row.kind
            if kind.startswith("desktop_"):
                resource = "desktop:" + payload.get("path", "")
            elif kind == "stop_preview":
                resource = "preview:" + payload.get("request", "")
            elif kind == "start_preview":
                resource = os.path.normcase(
                    payload.get("repository_id", "workspace") + ":" + payload.get("path", "")
                )
            else:
                resource = os.path.normcase(payload.get("path") or payload.get("repository_id", ""))
        # Overlapping directory resources also conflict, not just identical paths.
        for name, lock in self.locks.items():
            if lock.locked() and (
                resource == name or resource.startswith(name + os.sep) or name.startswith(resource + os.sep)
            ):
                raise ActionError("resource_writer_active")
        lock = self.locks.setdefault(resource, asyncio.Lock())
        async with lock:
            with self.sessions.begin() as session:
                row = session.get(ChatAction, action_id)
                assert row is not None
                if row.status != "approved":
                    raise ActionError("action_not_approved")
                self.validate_policy(session, row)
                self.validate_snapshot(row)
                row.status, row.version = "running", row.version + 1
                kind = row.kind
            try:
                result = await executor(action_id, kind, payload)
                status = "complete"
            except asyncio.CancelledError:
                self.finish(action_id, "interrupted", {"error": "server_shutdown; no automatic replay"})
                raise
            except (OSError, ValueError, RuntimeError) as exc:
                result, status = {"error": redact_text(str(exc))[:300]}, "failed"
            self.finish(action_id, status, result)
            return result

    def finish(self, action_id: str, status: str, result: dict[str, Any]) -> None:
        with self.sessions.begin() as session:
            row = session.get(ChatAction, action_id)
            assert row is not None
            row.status, row.result_json = status, json.dumps(result, ensure_ascii=False)
            row.version += 1
            row.finished_at = utc_now()
