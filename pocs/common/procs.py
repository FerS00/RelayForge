"""Windows Job Objects y auxiliares para vigilar árboles de procesos."""

from __future__ import annotations

import ctypes
import os
import subprocess
import time
from ctypes import wintypes
from pathlib import Path
from typing import Mapping

import psutil

_CREATE_SUSPENDED = 0x00000004
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_THREAD_SUSPEND_RESUME = 0x0002
_TRACKED: dict[tuple[int, float], dict[int, float]] = {}


class _BasicLimit(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in
                ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount",
                 "WriteTransferCount", "OtherTransferCount")]


class _ExtendedLimit(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimit), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


class JobObject:
    def __init__(self, kill_on_close: bool = True):
        if os.name != "nt":
            raise NotImplementedError("Windows Job Objects solo están disponibles en Windows")
        self._kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self._kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int,
                                                         ctypes.c_void_p, wintypes.DWORD]
        self._kernel.OpenProcess.restype = wintypes.HANDLE
        self._kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self._kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self._kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel.OpenThread.restype = wintypes.HANDLE
        self._kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel.ResumeThread.argtypes = [wintypes.HANDLE]
        self._kernel.ResumeThread.restype = wintypes.DWORD
        self._handle = self._kernel.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = _ExtendedLimit()
        if kill_on_close:
            info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = self._kernel.SetInformationJobObject(
            self._handle, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info)
        )
        if not ok:
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, pid: int) -> None:
        process = self._kernel.OpenProcess(0x0100 | 0x0001, False, pid)
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not self._kernel.AssignProcessToJobObject(self._handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            self._kernel.CloseHandle(process)

    def terminate(self, exit_code: int = 1) -> None:
        if self._handle and not self._kernel.TerminateJobObject(self._handle, exit_code):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self) -> None:
        if getattr(self, "_handle", None):
            self._kernel.CloseHandle(self._handle)
            self._handle = None

    def __enter__(self) -> JobObject:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def spawn_in_job(argv: list[str], job: JobObject, cwd: Path, stdout_path: Path, stderr_path: Path,
                 stdin_path: Path | None = None, env: Mapping[str, str] | None = None) -> subprocess.Popen:
    """Abre archivos para IO y asigna el proceso antes de reanudarlo.

    Si Windows no permite crear el proceso suspendido, se intenta un lanzamiento normal y la asignación
    ocurre inmediatamente después; en esa alternativa existe una pequeña ventana para crear descendientes.
    """
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stdin_file = stdin_path.open("rb") if stdin_path else subprocess.DEVNULL
    try:
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            try:
                proc = subprocess.Popen(argv, cwd=cwd, stdin=stdin_file, stdout=stdout_file, stderr=stderr_file,
                                        env=dict(env) if env is not None else None,
                                        creationflags=_CREATE_NEW_PROCESS_GROUP | _CREATE_SUSPENDED)
            except OSError:
                proc = subprocess.Popen(argv, cwd=cwd, stdin=stdin_file, stdout=stdout_file, stderr=stderr_file,
                                        env=dict(env) if env is not None else None,
                                        creationflags=_CREATE_NEW_PROCESS_GROUP)
                job.assign(proc.pid)
                return proc
            job.assign(proc.pid)
            thread_id = psutil.Process(proc.pid).threads()[0].id
            thread = job._kernel.OpenThread(_THREAD_SUSPEND_RESUME, False, thread_id)
            if not thread:
                job.terminate()
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if job._kernel.ResumeThread(thread) == 0xFFFFFFFF:
                    job.terminate()
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                job._kernel.CloseHandle(thread)
            return proc
    finally:
        if stdin_path:
            stdin_file.close()


def alive_descendants(root_pid: int, root_create_time: float) -> list[int]:
    try:
        root = psutil.Process(root_pid)
        if abs(root.create_time() - root_create_time) > 0.01:
            return []
        children = [child for child in root.children(recursive=True) if child.is_running()]
        _TRACKED.setdefault((root_pid, root_create_time), {}).update(
            {child.pid: child.create_time() for child in children}
        )
        return [child.pid for child in children]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []


def kill_tree_fallback(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15, check=False)


def wait_tree_gone(pid: int, create_time: float, timeout: float = 5) -> bool:
    deadline = time.monotonic() + timeout
    known = _TRACKED.get((pid, create_time), {})
    while time.monotonic() < deadline:
        try:
            root = psutil.Process(pid)
            root_alive = abs(root.create_time() - create_time) < 0.01 and root.is_running()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            root_alive = False
        children_alive = False
        for child_pid, child_created in known.items():
            try:
                child = psutil.Process(child_pid)
                if abs(child.create_time() - child_created) < 0.01 and child.is_running():
                    children_alive = True
            except psutil.NoSuchProcess:
                continue
            except psutil.AccessDenied:
                children_alive = True
        if not root_alive and not children_alive and not alive_descendants(pid, create_time):
            _TRACKED.pop((pid, create_time), None)
            return True
        time.sleep(0.05)
    return False
