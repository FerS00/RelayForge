from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import socket
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import psutil
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from relayforge.adapters.base import LaunchPlan, NormalizedEvent
from relayforge.core.deliverables import DeliverableError, Root, find_root, resolve, roots
from relayforge.core.event_sequence import next_seq
from relayforge.core.events import EventBus
from relayforge.core.ids import new_ulid
from relayforge.db.models import Event, Job, Preview, utc_now
from relayforge.process.supervisor import RunHandle, Supervisor
from relayforge.security.redact import redact_text
from relayforge.settings import Settings

_COMMANDS = {"npm", "pnpm", "yarn", "node", "python", "py", "uv", "bun", "deno"}
_ACTIVE = {"starting", "running"}
_TERMINAL_JOBS = {"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED", "CANCELLING"}
_START_TIMEOUT_SECONDS = 60
_MONITOR_INTERVAL_SECONDS = 5
_ACCESS_UPDATE_SECONDS = 30


class PreviewError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class PreviewService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        supervisor: Supervisor,
        settings: Settings,
        data_root: Path,
        event_bus: EventBus | None = None,
    ) -> None:
        self.sessions = sessions
        self.supervisor = supervisor
        self.settings = settings
        self.data_root = data_root
        self.event_bus = event_bus
        self.gateway_available = False
        self.gateway_error: str | None = (
            "preview_unavailable" if settings.container_mode else "preview_gateway_unavailable"
        )
        self._handles: dict[str, RunHandle] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_access: dict[str, float] = {}
        self._monitor_task: asyncio.Task[None] | None = None
        self.revoke_preview: Any = None

    def set_gateway_state(self, available: bool, error_code: str | None = None) -> None:
        self.gateway_available = available and not self.settings.container_mode
        self.gateway_error = (
            None
            if self.gateway_available
            else error_code
            or ("preview_unavailable" if self.settings.container_mode else "preview_gateway_unavailable")
        )

    def snapshot(self, session: Session, conversation_id: str, root_ref: str, rel: str) -> tuple[str, bool]:
        directory, _, manifest = self._target(session, conversation_id, root_ref, rel)
        kind = "command" if manifest is not None else "static"
        manifest_hash = (
            hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest is not None else "static"
        )
        value = f"{directory}|{manifest_hash}"
        return hashlib.sha256(value.encode("utf-8")).hexdigest(), kind == "command"

    async def start(
        self, conversation_id: str, root_ref: str, rel: str, action_id: str | None
    ) -> dict[str, Any]:
        root_ref = root_ref or "workspace"
        preview_id = new_ulid()
        lock = self._locks.setdefault(preview_id, asyncio.Lock())
        async with lock:
            if self.settings.container_mode:
                raise PreviewError("preview_unavailable")
            with self.sessions.begin() as session:
                directory, root, manifest = self._target(session, conversation_id, root_ref, rel)
                kind = "command" if manifest is not None else "static"
                argv: list[str] | None = None
                ready_path = "/"
                job_id = root_ref.removeprefix("job:") if root_ref.startswith("job:") else None
                now = utc_now()
                row = Preview(
                    id=preview_id,
                    conversation_id=conversation_id,
                    action_id=action_id,
                    job_id=job_id,
                    root_path=str(directory),
                    kind=kind,
                    argv_json=json.dumps(argv or [], ensure_ascii=False),
                    status="starting",
                    last_access_at=now,
                    created_at=now,
                    version=0,
                )
                session.add(row)
                session.flush()
                failure = self.gateway_error if not self.gateway_available else None
                count = (
                    session.scalar(
                        select(func.count()).select_from(Preview).where(Preview.status.in_(_ACTIVE))
                    )
                    or 0
                )
                if failure is None and count > self.settings.preview_max_active:
                    failure = "preview_limit_reached"
                if failure is None and kind == "static":
                    try:
                        index = resolve(root, _relative_from_root(root, directory, "index.html"))
                        if not index.is_file():
                            failure = "preview_index_missing"
                    except DeliverableError:
                        failure = "preview_index_missing"
                port: int | None = None
                if failure is None and kind == "command":
                    try:
                        port = self._allocate_port(session)
                    except PreviewError as exc:
                        failure = exc.code
                    if failure is None and manifest is not None:
                        try:
                            argv, ready_path = _parse_manifest(manifest)
                            resolved = shutil.which(argv[0])
                            if resolved is None:
                                failure = "preview_command_not_found"
                            else:
                                argv[0] = resolved
                                argv = [str(port) if item == "{port}" else item for item in argv]
                                row.argv_json = json.dumps(argv, ensure_ascii=False)
                        except PreviewError as exc:
                            failure = exc.code
                row.port = port
                if failure:
                    self._transition(session, row, "failed", failure)
                else:
                    self._record_event(session, row)
                stored = self._serialize(row)
            if failure:
                raise PreviewError(failure)
            if kind == "static":
                with self.sessions.begin() as session:
                    running_row = session.get(Preview, preview_id)
                    assert running_row is not None
                    self._transition(session, running_row, "running", None)
                    stored = self._serialize(running_row)
                return self._tool_result(stored)

            assert port is not None and argv is not None
            await self._start_command(preview_id, directory, argv, port, ready_path)
            with self.sessions() as session:
                started_row = session.get(Preview, preview_id)
                assert started_row is not None
                return self._tool_result(self._serialize(started_row))

    async def _start_command(
        self, preview_id: str, directory: Path, argv: list[str], port: int, ready_path: str
    ) -> None:
        folder = self.data_root / "previews" / preview_id
        stdout_path, stderr_path = folder / "stdout.log", folder / "stderr.log"
        environment = os.environ.copy()
        environment.update({"PORT": str(port), "HOST": "127.0.0.1", "BROWSER": "none"})
        plan = LaunchPlan(tuple(argv), directory, "", environment)
        try:
            handle = await asyncio.to_thread(
                self.supervisor.start, plan, output_path=stdout_path, stderr_path=stderr_path
            )
        except (OSError, RuntimeError, ValueError):
            self._mark_failed(preview_id, "preview_process_exited")
            raise PreviewError("preview_process_exited") from None
        self._handles[preview_id] = handle
        with self.sessions.begin() as session:
            row = session.get(Preview, preview_id)
            assert row is not None
            row.pid, row.pid_create_time, row.log_path = handle.pid, handle.create_time, str(stdout_path)
            row.version += 1
        deadline = asyncio.get_running_loop().time() + _START_TIMEOUT_SECONDS
        while asyncio.get_running_loop().time() < deadline:
            if await asyncio.to_thread(_tcp_ready, port, ready_path):
                with self.sessions.begin() as session:
                    row = session.get(Preview, preview_id)
                    assert row is not None
                    self._transition(session, row, "running", None)
                return
            if self.supervisor.exit_code(handle) is not None:
                await self._stop_process(preview_id, handle.pid, handle.create_time)
                self._mark_failed(preview_id, "preview_process_exited")
                raise PreviewError("preview_process_exited")
            await asyncio.sleep(0.1)
        await self._stop_process(preview_id, handle.pid, handle.create_time)
        self._mark_failed(preview_id, "preview_start_timeout")
        raise PreviewError("preview_start_timeout")

    def stop_sync(self, preview_id: str, reason: str = "user") -> dict[str, Any]:
        with self.sessions() as session:
            row = session.get(Preview, preview_id)
            if row is None:
                raise PreviewError("preview_not_found")
            process = (row.pid, row.pid_create_time)
            status = row.status
        if status in {"stopped", "failed", "interrupted"}:
            return self._serialize_by_id(preview_id)
        self._stop_process_sync(preview_id, *process)
        with self.sessions.begin() as session:
            row = session.get(Preview, preview_id)
            if row is None:
                raise PreviewError("preview_not_found")
            if row.status not in {"stopped", "failed", "interrupted"}:
                code = reason if reason.startswith("preview_") else None
                self._transition(session, row, "stopped", code)
            result = self._serialize(row)
        self._revoke(preview_id)
        return result

    async def stop(self, preview_id: str, reason: str = "user") -> dict[str, Any]:
        lock = self._locks.setdefault(preview_id, asyncio.Lock())
        async with lock:
            return await asyncio.to_thread(self.stop_sync, preview_id, reason)

    async def startup(self) -> None:
        with self.sessions() as session:
            rows = session.scalars(select(Preview).where(Preview.status.in_(_ACTIVE))).all()
            identities = [(row.id, row.pid, row.pid_create_time) for row in rows]
        for preview_id, pid, create_time in identities:
            if pid is not None and create_time is not None:
                await asyncio.to_thread(self.supervisor.terminate_process_identity, pid, create_time)
            with self.sessions.begin() as session:
                row = session.get(Preview, preview_id)
                if row is not None and row.status in _ACTIVE:
                    self._transition(session, row, "interrupted", None)

    def start_monitor(self) -> None:
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self._monitor())

    async def shutdown(self) -> None:
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            await asyncio.gather(self._monitor_task, return_exceptions=True)
            self._monitor_task = None
        with self.sessions() as session:
            ids = list(session.scalars(select(Preview.id).where(Preview.status.in_(_ACTIVE))))
        for preview_id in ids:
            await self.stop(preview_id, "backend_shutdown")

    def list_for_conversation(self, conversation_id: str) -> list[dict[str, Any]]:
        with self.sessions() as session:
            items = session.scalars(
                select(Preview)
                .where(Preview.conversation_id == conversation_id)
                .order_by(Preview.created_at.desc(), Preview.id)
            ).all()
            available_roots = roots(session, conversation_id)
            serialized: list[dict[str, Any]] = []
            for item in items:
                root_ref = f"job:{item.job_id}" if item.job_id else "workspace"
                base = next((root for root in available_roots if root.ref == root_ref), None)
                try:
                    path = Path(item.root_path).relative_to(base.path).as_posix() if base else ""
                except ValueError:
                    path = ""
                serialized.append(
                    {
                        **self._serialize(item),
                        "root": root_ref,
                        "path": "" if path == "." else path,
                        "log_tail": self._log_tail(item.log_path),
                    }
                )
            return serialized

    def gateway_preview(self, preview_id: str) -> dict[str, Any] | None:
        with self.sessions() as session:
            row = session.get(Preview, preview_id)
            if row is None:
                return None
            return {
                "id": row.id,
                "conversation_id": row.conversation_id,
                "root_path": row.root_path,
                "kind": row.kind,
                "port": row.port,
                "status": row.status,
                "job_id": row.job_id,
            }

    def touch(self, preview_id: str) -> None:
        now_mono = time.monotonic()
        if now_mono - self._last_access.get(preview_id, 0.0) < _ACCESS_UPDATE_SECONDS:
            return
        with self.sessions.begin() as session:
            row = session.get(Preview, preview_id)
            if row is None or row.status != "running":
                return
            try:
                last = datetime.fromisoformat(row.last_access_at.replace("Z", "+00:00"))
            except ValueError:
                last = datetime.min.replace(tzinfo=UTC)
            if (datetime.now(UTC) - last).total_seconds() >= _ACCESS_UPDATE_SECONDS:
                row.last_access_at = utc_now()
                row.version += 1
                self._last_access[preview_id] = now_mono

    def access_allowed(self, preview_id: str) -> bool:
        data = self.gateway_preview(preview_id)
        return data is not None and data["status"] == "running"

    def snapshot_for_action(self, conversation_id: str, root_ref: str, rel: str) -> tuple[str, bool]:
        with self.sessions() as session:
            return self.snapshot(session, conversation_id, root_ref, rel)

    def _target(
        self, session: Session, conversation_id: str, root_ref: str, rel: str
    ) -> tuple[Path, Root, Path | None]:
        try:
            root = find_root(session, conversation_id, root_ref)
            directory = resolve(root, rel)
        except DeliverableError as exc:
            raise PreviewError(exc.code) from None
        if not directory.is_dir():
            raise PreviewError("preview_path_not_directory")
        manifest: Path | None = None
        try:
            manifest = resolve(root, _relative_from_root(root, directory, "relayforge-preview.json"))
        except DeliverableError as exc:
            if exc.code != "file_not_found":
                raise PreviewError(exc.code) from None
        return directory, root, manifest

    def _allocate_port(self, session: Session) -> int:
        assigned = set(
            session.scalars(
                select(Preview.port).where(Preview.status.in_(_ACTIVE), Preview.port.is_not(None))
            )
        )
        first, last = self.settings.preview_port_range
        for port in range(first, last + 1):
            if port in assigned:
                continue
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                else:
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind(("127.0.0.1", port))
                return port
            except OSError:
                pass
            finally:
                probe.close()
        raise PreviewError("preview_ports_exhausted")

    async def _monitor(self) -> None:
        while True:
            await asyncio.sleep(_MONITOR_INTERVAL_SECONDS)
            await self.monitor_once()

    async def monitor_once(self) -> None:
        with self.sessions() as session:
            items = session.scalars(select(Preview).where(Preview.status == "running")).all()
            candidates = [
                (item.id, item.pid, item.pid_create_time, item.kind, item.job_id, item.last_access_at)
                for item in items
            ]
            jobs = {
                row.id: row.status
                for row in session.scalars(
                    select(Job).where(Job.id.in_([item[4] for item in candidates if item[4]]))
                )
            }
        for preview_id, pid, create_time, kind, job_id, last_access in candidates:
            if job_id and jobs.get(job_id) in _TERMINAL_JOBS:
                await self.stop(preview_id, "job_finished")
                continue
            if (
                kind == "command"
                and pid is not None
                and create_time is not None
                and not await asyncio.to_thread(_identity_running, pid, create_time)
            ):
                await self._stop_process(preview_id, pid, create_time)
                self._mark_failed(preview_id, "preview_process_exited")
                self._revoke(preview_id)
                continue
            try:
                last = datetime.fromisoformat(last_access.replace("Z", "+00:00"))
            except ValueError:
                last = datetime.min.replace(tzinfo=UTC)
            if (datetime.now(UTC) - last).total_seconds() >= self.settings.preview_idle_seconds:
                await self.stop(preview_id, "preview_idle_timeout")

    def _stop_process_sync(self, preview_id: str, pid: int | None, create_time: float | None) -> None:
        handle = self._handles.pop(preview_id, None)
        if handle is not None:
            self.supervisor.kill(handle)
        elif pid is not None and create_time is not None:
            self.supervisor.terminate_process_identity(pid, create_time)

    async def _stop_process(self, preview_id: str, pid: int | None, create_time: float | None) -> None:
        await asyncio.to_thread(self._stop_process_sync, preview_id, pid, create_time)

    def _mark_failed(self, preview_id: str, code: str) -> None:
        with self.sessions.begin() as session:
            row = session.get(Preview, preview_id)
            if row is not None and row.status in _ACTIVE:
                self._transition(session, row, "failed", code)

    def _transition(self, session: Session, row: Preview, status: str, error_code: str | None) -> None:
        row.status, row.error_code = status, error_code
        row.version += 1
        if status in {"stopped", "failed", "interrupted"}:
            row.finished_at = utc_now()
        self._record_event(session, row)

    def _record_event(self, session: Session, row: Preview) -> None:
        seq = next_seq(session, row.conversation_id)
        timestamp = utc_now()
        data = {
            "id": row.id,
            "status": row.status,
            "kind": row.kind,
            "error_code": row.error_code,
        }
        session.add(
            Event(
                conversation_id=row.conversation_id,
                seq=seq,
                ts=timestamp,
                type="preview.updated",
                actor="core",
                job_id=row.job_id,
                payload_json=json.dumps({"data": data}, ensure_ascii=False, separators=(",", ":")),
            )
        )
        if self.event_bus is not None:
            self.event_bus.publish(
                row.conversation_id,
                NormalizedEvent("preview.updated", "core", None, {**data, "_seq": seq}, timestamp),
            )

    def _serialize(self, row: Preview) -> dict[str, Any]:
        return {
            "id": row.id,
            "status": row.status,
            "kind": row.kind,
            "port": row.port,
            "error_code": row.error_code,
            "created_at": row.created_at,
        }

    def _serialize_by_id(self, preview_id: str) -> dict[str, Any]:
        with self.sessions() as session:
            row = session.get(Preview, preview_id)
            if row is None:
                raise PreviewError("preview_not_found")
            return self._serialize(row)

    @staticmethod
    def _tool_result(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "preview_id": row["id"],
            "status": row["status"],
            "kind": row["kind"],
            "url_hint": "abre el panel Entregables",
        }

    def _log_tail(self, log_path: str | None) -> list[str]:
        if not log_path:
            return []
        lines: list[str] = []
        for path in (Path(log_path), Path(log_path).with_name("stderr.log")):
            try:
                with path.open("rb") as stream:
                    stream.seek(max(0, path.stat().st_size - 64 * 1024))
                    raw = stream.read().decode("utf-8", errors="replace")
                lines.extend(redact_text(line) for line in raw.splitlines())
            except OSError:
                continue
        return lines[-20:]

    def _revoke(self, preview_id: str) -> None:
        if callable(self.revoke_preview):
            self.revoke_preview(preview_id)


def _parse_manifest(path: Path) -> tuple[list[str], str]:
    try:
        if path.stat().st_size > 32 * 1024:
            raise PreviewError("preview_manifest_invalid")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except PreviewError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise PreviewError("preview_manifest_invalid") from None
    if not isinstance(payload, dict) or set(payload) != {"argv", "ready_path"}:
        raise PreviewError("preview_manifest_invalid")
    argv, ready_path = payload["argv"], payload["ready_path"]
    if (
        not isinstance(argv, list)
        or not 1 <= len(argv) <= 32
        or any(not isinstance(item, str) or len(item) > 512 or "\x00" in item for item in argv)
        or argv[0] not in _COMMANDS
        or not isinstance(ready_path, str)
        or len(ready_path) > 2048
        or "\x00" in ready_path
        or "\r" in ready_path
        or "\n" in ready_path
        or not ready_path.startswith("/")
        or ".." in ready_path.split("/")
    ):
        raise PreviewError("preview_manifest_invalid")
    return list(argv), ready_path


def _relative_from_root(root: Root, directory: Path, name: str) -> str:
    relative = directory.relative_to(root.path).as_posix()
    return f"{relative}/{name}" if relative != "." else name


def _tcp_ready(port: int, ready_path: str) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2) as connection:
            target = quote(ready_path, safe="/%:@-._~!$&'()*+,;=")
            connection.sendall(
                f"GET {target} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode("ascii")
            )
            return True
    except OSError:
        return False


def _identity_running(pid: int, create_time: float) -> bool:
    try:
        process = psutil.Process(pid)
        return abs(process.create_time() - create_time) <= 0.01 and bool(process.is_running())
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        return True
