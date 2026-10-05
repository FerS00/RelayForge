from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from relayforge.adapters.antigravity.adapter import AntigravityAdapter
from relayforge.adapters.base import AuditResult
from relayforge.core.jobs import JobService
from relayforge.core.states import JobStatus


class Auditor(Protocol):
    async def audit(
        self,
        worktree: Path,
        changed_paths: list[str],
        commands: list[dict[str, Any]],
        iteration: int,
        diff_text: str = "",
        profile: str = "default",
    ) -> AuditResult: ...


class AuditWorkflow:
    def __init__(self, service: JobService, auditor: Auditor) -> None:
        self.service = service
        self.auditor = auditor

    async def run_iteration(
        self, job_id: str, *, profile: str | None = None
    ) -> tuple[bool, list[dict[str, Any]]]:
        job = self.service.get_job(job_id)
        if job is None:
            raise RuntimeError("job_missing")
        iteration = int(job["iteration"])
        if job["status"] == JobStatus.TRIAGING.value:
            audit_context = {"diff": job["diff"], "max_iterations": job["max_iterations"]}
            findings = [finding for finding in job.get("findings", []) if finding["audit_no"] == iteration]
            return await self._triage(job_id, job, findings, audit_context, iteration)
        _context, step_id, audit_context = self.service.audit_context(job_id, iteration)
        if job["status"] != JobStatus.AUDITING.value:
            self.service.transition(job_id, JobStatus.AUDITING)
        auditor = self.auditor
        if isinstance(auditor, AntigravityAdapter) and job.get("audit_model"):
            auditor = AntigravityAdapter(
                auditor.executable, str(job["audit_model"]), auditor.effort, auditor.timeout_seconds
            )
        result = await auditor.audit(
            Path(audit_context["worktree"]),
            audit_context["paths"],
            self.service.check_commands(job_id),
            iteration,
            str(audit_context["diff"]),
            profile=profile or ("security" if job["workflow"] == "security" else "default"),
        )
        findings = self.service.record_audit(job_id, step_id, iteration, result)
        if result.verdict == "BLOCKED":
            raise RuntimeError("audit_blocked")
        if result.verdict in {"APPROVED", "APPROVED_WITH_NOTES"} and not findings:
            return True, []
        if not findings:
            raise RuntimeError("audit_rejected_without_findings")
        self.service.transition(job_id, JobStatus.TRIAGING)
        return await self._triage(job_id, job, findings, audit_context, iteration)

    async def _triage(
        self,
        job_id: str,
        job: dict[str, Any],
        findings: list[dict[str, Any]],
        audit_context: dict[str, Any],
        iteration: int,
    ) -> tuple[bool, list[dict[str, Any]]]:
        triage_context = self.service.triage_context(job_id, iteration)
        triage_succeeded = False
        try:
            triage = await self.service.planner_for(job).triage(
                triage_context, findings, str(audit_context["diff"]), []
            )
            accepted = self.service.record_triage(job_id, findings, triage)
            triage_succeeded = True
        finally:
            self.service.finish_triage_step(triage_context, "SUCCEEDED" if triage_succeeded else "FAILED")
        if not accepted:
            return True, []
        if iteration >= int(audit_context["max_iterations"]):
            self.service.set_approval_kind(job_id, "iteration_limit")
            self.service.transition(job_id, JobStatus.WAITING_APPROVAL)
            return False, []
        self.service.transition(job_id, JobStatus.REVISING)
        next_iteration = self.service.increment_iteration(job_id)
        self.service.mark_findings_fixed(job_id, [str(item["id"]) for item in accepted], next_iteration)
        return False, accepted
