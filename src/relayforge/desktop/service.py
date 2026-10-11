from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Protocol

import psutil
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from relayforge.core.ids import new_ulid
from relayforge.db.models import DesktopTarget, utc_now
from relayforge.desktop.policy import KIND_OPERATION
from relayforge.settings import Settings

WORKER_SCRIPT = Path(__file__).with_name("worker.ps1")


class DesktopError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class DesktopWorker(Protocol):
    async def call(self, request: dict[str, Any], timeout: float) -> dict[str, Any]: ...


class PowerShellWorker:
    """One short-lived worker per operation.

    It deliberately runs outside the Supervisor's kill-on-close job object: a
    launched application must outlive the worker that started it.
    """

    async def call(self, request: dict[str, Any], timeout: float) -> dict[str, Any]:
        argv = ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(WORKER_SCRIPT)]
        try:
            completed = await asyncio.to_thread(
                subprocess.run,
                argv,
                input=json.dumps(request, ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            raise DesktopError("desktop_action_timeout") from None
        except OSError:
            raise DesktopError("desktop_worker_unavailable") from None
        lines = completed.stdout.strip().splitlines()
        try:
            result = json.loads(lines[-1]) if lines else None
        except json.JSONDecodeError:
            result = None
        if not isinstance(result, dict):
            raise DesktopError("desktop_worker_unavailable")
        return result


class DesktopService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        worker: DesktopWorker,
        settings: Settings,
        attachments: Any = None,
    ) -> None:
        self.sessions = sessions
        self.worker = worker
        self.settings = settings
        self.attachments = attachments

    @property
    def available(self) -> bool:
        return self.settings.desktop_enabled and not self.settings.container_mode and os.name == "nt"

    def apps(self) -> dict[str, Path]:
        if self.settings.desktop_apps:
            return dict(self.settings.desktop_apps)
        system_root = Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
        return {"notepad": system_root / "System32" / "notepad.exe"}

    def allowed_dirs(self) -> tuple[Path, ...]:
        return self.settings.desktop_allowed_dirs or (self.settings.home / "desktop-files",)

    def app_snapshot(self, app: str) -> str:
        executable = self.apps().get(app)
        if executable is None or not executable.is_file():
            raise DesktopError("desktop_app_not_allowed")
        return f"desktop-app:{app}:{executable}"

    def target_snapshot(self, conversation_id: str, target_id: str) -> str:
        with self.sessions() as session:
            row = self._target(session, conversation_id, target_id)
            return f"desktop-target:{row.id}:{row.pid}:{row.pid_create_time}:{row.hwnd}"

    async def call(self, request: dict[str, Any]) -> dict[str, Any]:
        if not self.available:
            raise DesktopError("desktop_unavailable")
        result = await self.worker.call(request, float(self.settings.desktop_action_timeout))
        if result.get("ok") is not True:
            raise DesktopError(str(result.get("error") or "desktop_worker_error")[:64])
        return result

    async def execute(
        self, conversation_id: str, action_id: str, kind: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if kind == "desktop_launch":
            return await self.launch(conversation_id, action_id, payload["path"])
        from relayforge.desktop.policy import parse_request

        request_data = payload.get("request_data")
        if request_data is None:
            request_data = parse_request(kind, payload.get("request", ""))
        return await self.perform(conversation_id, payload["path"], kind, request_data)

    async def launch(self, conversation_id: str, action_id: str, app: str) -> dict[str, Any]:
        self.app_snapshot(app)
        probe = await self.call({"op": "probe"})
        if not probe.get("interactive") or probe.get("locked"):
            raise DesktopError("desktop_unavailable")
        if probe.get("elevated"):
            raise DesktopError("runtime_elevated")
        result = await self.call({"op": "launch", "exe": str(self.apps()[app])})
        row = DesktopTarget(
            id=new_ulid(),
            conversation_id=conversation_id,
            action_id=action_id,
            app=app,
            pid=int(result["pid"]),
            pid_create_time=float(result["create_time"]),
            hwnd=int(result["hwnd"]),
            title=str(result.get("title", ""))[:200],
            status="open",
        )
        with self.sessions.begin() as session:
            session.add(row)
            session.flush()
            return {"target_id": row.id, "app": app, "title": row.title, "status": "open"}

    async def perform(
        self, conversation_id: str, target_id: str, kind: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        operation = KIND_OPERATION.get(kind)
        if operation is None:
            raise DesktopError("desktop_kind_invalid")
        with self.sessions() as session:
            row = self._target(session, conversation_id, target_id)
            target = {"pid": row.pid, "create_time": row.pid_create_time, "hwnd": row.hwnd}
        try:
            result = await self.call({"op": operation, "target": target, **request})
        except DesktopError as exc:
            if exc.code == "target_changed":
                self._set_status(target_id, "lost")
            raise
        result.pop("ok", None)
        if operation == "capture":
            encoded = str(result.pop("png_base64", ""))
            if self.attachments is None or not encoded:
                raise DesktopError("capture_failed")
            stored = self.attachments.create(conversation_id, f"captura-{target_id}.png", encoded)
            result["attachment_id"] = stored["id"]
        if operation == "close":
            self._set_status(target_id, "closed")
        return {"target_id": target_id, "operation": operation, **result}

    def list_open(self, conversation_id: str) -> list[dict[str, Any]]:
        with self.sessions() as session:
            rows = session.scalars(
                select(DesktopTarget).where(
                    DesktopTarget.conversation_id == conversation_id, DesktopTarget.status == "open"
                )
            ).all()
            return [{"target_id": row.id, "app": row.app, "title": row.title} for row in rows]

    async def close_targets_for_conversation(self, conversation_id: str) -> None:
        from relayforge.process.supervisor import Supervisor

        for item in self.list_open(conversation_id):
            target_id = item["target_id"]
            with contextlib.suppress(Exception):
                await self.perform(conversation_id, target_id, "desktop_close", {})
            with self.sessions() as session:
                row = session.get(DesktopTarget, target_id)
                if row is not None and row.status == "open":
                    if _identity_matches(row.pid, row.pid_create_time):
                        Supervisor.terminate_process_identity(row.pid, row.pid_create_time)
                    self._set_status(target_id, "closed")

    def startup(self) -> None:
        with self.sessions.begin() as session:
            for row in session.scalars(select(DesktopTarget).where(DesktopTarget.status == "open")):
                if not _identity_matches(row.pid, row.pid_create_time):
                    row.status, row.closed_at = "lost", utc_now()
        for directory in self.allowed_dirs():
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _target(session: Session, conversation_id: str, target_id: str) -> DesktopTarget:
        row = session.get(DesktopTarget, target_id)
        if row is None or row.conversation_id != conversation_id or row.status != "open":
            raise DesktopError("desktop_target_not_found")
        return row

    def _set_status(self, target_id: str, status: str) -> None:
        with self.sessions.begin() as session:
            row = session.get(DesktopTarget, target_id)
            if row is not None and row.status == "open":
                row.status, row.closed_at = status, utc_now()


def _identity_matches(pid: int, create_time: float) -> bool:
    try:
        return bool(abs(psutil.Process(pid).create_time() - create_time) <= 0.01)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False
