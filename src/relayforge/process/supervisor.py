from __future__ import annotations

import os
import subprocess
import threading
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

import psutil

from relayforge.adapters.base import LaunchPlan
from relayforge.platform.windows import close_job, create_kill_on_close_job

_MAX_LINE = 8 * 1024 * 1024
_CMD_FORBIDDEN = frozenset('&|<>^%"\r\n')


@dataclass
class RunHandle:
    pid: int
    create_time: float
    output_path: Path
    stderr_path: Path
    process: subprocess.Popen[bytes] = field(repr=False)
    job_handle: int = field(repr=False)
    offset: int = 0
    partial: bytes = b""
    dropping: bool = False
    oversized_lines: int = 0


class Supervisor:
    def __init__(self) -> None:
        self._runs: dict[tuple[int, float], RunHandle] = {}
        self._lock = threading.RLock()

    def start(self, plan: LaunchPlan, *, output_path: Path, stderr_path: Path) -> RunHandle:
        argv = list(plan.argv)
        command_line: str | list[str] = argv
        if os.name == "nt" and argv[0].lower().endswith((".cmd", ".bat")):
            if any(any(char in arg for char in _CMD_FORBIDDEN) for arg in argv):
                raise ValueError("Argumentos no admitidos para lanzadores por lotes.")
            command_line = f'cmd.exe /d /s /c "{subprocess.list2cmdline(argv)}"'
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.touch()
        stderr_path.touch()
        with output_path.open("ab") as stdout_file, stderr_path.open("ab") as stderr_file:
            process = subprocess.Popen(
                command_line,
                cwd=plan.cwd,
                stdin=subprocess.PIPE,
                stdout=stdout_file,
                stderr=stderr_file,
                env=dict(plan.env) if plan.env else None,
                shell=False,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        try:
            job = create_kill_on_close_job(int(process._handle))  # type: ignore[attr-defined]
            if plan.stdin_text:
                assert process.stdin is not None
                process.stdin.write(plan.stdin_text.encode("utf-8"))
            if process.stdin is not None:
                process.stdin.close()
            try:
                create_time = psutil.Process(process.pid).create_time()
            except psutil.NoSuchProcess:
                create_time = 0.0
            handle = RunHandle(process.pid, create_time, output_path, stderr_path, process, job)
            with self._lock:
                self._runs[(handle.pid, handle.create_time)] = handle
            return handle
        except BaseException:
            process.kill()
            process.wait()
            raise

    def read_lines(self, handle: RunHandle) -> list[bytes]:
        with handle.output_path.open("rb") as output:
            output.seek(handle.offset)
            data = output.read()
            handle.offset = output.tell()
        if not data:
            return []
        pending = handle.partial + data
        parts = pending.split(b"\n")
        handle.partial = parts.pop()
        lines: list[bytes] = []
        for part in parts:
            if handle.dropping:
                handle.dropping = False
                continue
            if len(part) > _MAX_LINE:
                handle.oversized_lines += 1
                continue
            lines.append(part + b"\n")
        if len(handle.partial) > _MAX_LINE:
            handle.partial = b""
            handle.dropping = True
            handle.oversized_lines += 1
        return lines

    def exit_code(self, handle: RunHandle) -> int | None:
        return handle.process.poll()

    def kill(self, handle: RunHandle) -> None:
        with self._lock:
            key = (handle.pid, handle.create_time)
            if self._runs.pop(key, None) is None:
                return
        deadline = time.monotonic() + 5
        try:
            descendants = psutil.Process(handle.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            descendants = []
        close_job(handle.job_handle)
        handle.job_handle = 0
        try:
            handle.process.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            with suppress(OSError):
                handle.process.kill()
            handle.process.wait(timeout=max(0, deadline - time.monotonic()))
        if descendants:
            _, alive = psutil.wait_procs(descendants, timeout=max(0, deadline - time.monotonic()))
            if alive:
                for process in alive:
                    with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                        process.kill()
                _, alive = psutil.wait_procs(alive, timeout=max(0, deadline - time.monotonic()))
            if alive:
                raise TimeoutError("No terminaron todos los procesos descendientes en 5 segundos.")

    def kill_all(self) -> None:
        with self._lock:
            handles = list(self._runs.values())
        for handle in handles:
            self.kill(handle)
