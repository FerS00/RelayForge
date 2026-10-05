from __future__ import annotations

import asyncio
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from relayforge.adapters.checks import CheckCommand, ChecksAdapter
from relayforge.core.jobs import JobService
from relayforge.process.supervisor import RunHandle, Supervisor

_MAX_OUTPUT_BYTES = 16 * 1024 * 1024


class ChecksWorkflow:
    def __init__(self, service: JobService, supervisor: Supervisor) -> None:
        self.service = service
        self.supervisor = supervisor

    async def run(self, job_id: str, worktree: Path) -> bool:
        raw_commands = self.service.check_commands(job_id)
        commands = ChecksAdapter.parse_many(raw_commands)
        if not commands:
            return True
        step_id = self.service.start_checks(job_id)
        results: list[dict[str, Any]] = []
        for command in commands:
            result = await self._run_one(job_id, command, worktree)
            results.append(result)
            if result["status"] != "passed":
                break
        self.service.finish_checks(job_id, step_id, results)
        return all(result["status"] == "passed" for result in results)

    async def _run_one(self, job_id: str, command: CheckCommand, worktree: Path) -> dict[str, Any]:
        plan = ChecksAdapter.build_run(command, worktree)
        started = time.monotonic()
        handle: RunHandle | None = None
        status = "failed"
        exit_code: int | None = None
        counts: dict[str, int] | None = None
        with tempfile.TemporaryDirectory(prefix="relayforge-check-") as temporary:
            output_path = Path(temporary) / "stdout.log"
            stderr_path = Path(temporary) / "stderr.log"
            try:
                handle = await self.supervisor.start_async(
                    plan, output_path=output_path, stderr_path=stderr_path
                )
                self.service.update_step_runtime(
                    job_id, "checks", pid=handle.pid, pid_create_time=handle.create_time
                )
                heartbeat = time.monotonic()
                while self.supervisor.exit_code(handle) is None:
                    if output_path.stat().st_size + stderr_path.stat().st_size > _MAX_OUTPUT_BYTES:
                        status = "output_limit"
                        break
                    if time.monotonic() - started >= command.timeout_seconds:
                        status = "timeout"
                        break
                    if time.monotonic() - heartbeat >= 10:
                        self.service.heartbeat(job_id, "checks")
                        heartbeat = time.monotonic()
                    await asyncio.sleep(0.05)
                if status not in {"timeout", "output_limit"}:
                    exit_code = self.supervisor.exit_code(handle)
                    status = "passed" if exit_code == 0 else "failed"
            except (OSError, ValueError, subprocess.SubprocessError):
                status = "start_failed"
            finally:
                if handle is not None:
                    try:
                        await asyncio.to_thread(self.supervisor.kill, handle)
                    except TimeoutError:
                        status = "orphan_process"
                    self.service.update_step_runtime(job_id, "checks")
            if status not in {"timeout", "output_limit", "start_failed"}:
                total_output = output_path.stat().st_size + stderr_path.stat().st_size
                if total_output > _MAX_OUTPUT_BYTES:
                    status = "output_limit"
                else:
                    output = output_path.read_text(encoding="utf-8", errors="replace")
                    counts = ChecksAdapter.junit_counts(worktree, command.argv)
                    if counts is None:
                        counts = ChecksAdapter.summarize_output(output)
        return {
            "name": command.name,
            "status": status,
            "exit_code": exit_code,
            "duration_seconds": round(time.monotonic() - started, 3),
            "counts": counts,
        }
