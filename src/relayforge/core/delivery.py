from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from relayforge.core.approvals import ApprovalService
from relayforge.core.jobs import JobService
from relayforge.core.policy import PolicyEngine, PolicyOperation
from relayforge.core.states import JobStatus
from relayforge.git.delivery import GitDelivery
from relayforge.git.operations import GitError
from relayforge.security.redact import redact_text


class DeliveryWorkflow:
    def __init__(
        self,
        jobs: JobService,
        approvals: ApprovalService,
        policy: PolicyEngine,
        git_delivery: GitDelivery,
        output_root: Path,
    ) -> None:
        self.jobs = jobs
        self.approvals = approvals
        self.policy = policy
        self.git_delivery = git_delivery
        self.output_root = output_root

    def prepare(self, job_id: str) -> dict[str, Any]:
        context = self.jobs.delivery_context(job_id)
        if context is None:
            raise RuntimeError("delivery_context_missing")
        if context["status"] not in {JobStatus.AUDITING.value, JobStatus.FINAL_REVIEW.value}:
            raise RuntimeError("delivery_state_invalid")
        if context["status"] != JobStatus.FINAL_REVIEW.value:
            self.jobs.transition(job_id, JobStatus.FINAL_REVIEW)
        worktree = Path(str(context["worktree_path"])).resolve(strict=True)
        self.git_delivery.git(worktree, "add", "-N", "--", ".")
        current_diff = self.git_delivery.git(
            worktree, "diff", "--no-ext-diff", "--no-color", "HEAD", timeout=60
        )
        diff_hash = self.git_delivery.diff_hash(current_diff)
        if self.git_delivery.diff_hash(str(context["diff"])) != diff_hash:
            raise RuntimeError("delivery_diff_changed")
        branch = str(context["branch"])
        protected = branch == str(context["default_branch"])
        try:
            remote_url = self.git_delivery.git(worktree, "remote", "get-url", "origin")
        except GitError:
            remotes = self.git_delivery.git(worktree, "remote").splitlines()
            if "origin" in remotes:
                raise
            report = {
                "job_id": job_id,
                "branch": branch,
                "diff_hash": diff_hash,
                "changed_paths": context["paths"],
                "diff_state": "modified" if context["paths"] else "clean",
                "delivery": "not_configured",
                "risks": [],
            }
            self._write_report(job_id, report)
            self.jobs.record_job_event(
                job_id,
                "final_review.created",
                "core",
                None,
                {**report, "artifact": f"jobs/{job_id}/final-review.md"},
            )
            self.jobs.transition(job_id, JobStatus.COMPLETED)
            return {"decision": "allow", "no_delivery": True}
        operation_name = "git.push_protected_branch" if protected else "git.push"
        commit_message = f"Job {context['number']}: {context['title']}"
        operation: dict[str, Any] = {
            "agent": "core",
            "role": "delivery",
            "repo": str(context["repository_id"]),
            "workflow": str(context["workflow"]),
            "tool": "git",
            "operation": operation_name,
            "target": f"origin:refs/heads/{branch}",
            "risk": "high",
            "branch": branch,
            "remote": "origin",
            "remote_fingerprint": self.git_delivery.remote_fingerprint(remote_url),
            "message": commit_message,
            "paths": list(context["paths"]),
        }
        evaluated = self.policy.evaluate(
            PolicyOperation(
                agent="core",
                role="delivery",
                repo=str(context["repository_id"]),
                workflow=str(context["workflow"]),
                tool="git",
                operation=operation_name,
                target=str(operation["target"]),
                risk="high",
                paths=tuple(str(item) for item in context["paths"]),
            ),
            profile=str(context["profile"]),
        )
        if evaluated.workflow != context["workflow"]:
            operation["workflow"] = evaluated.workflow
        if evaluated.decision == "ask" and self.approvals.grant_allows(job_id, operation):
            evaluated = type(evaluated)("allow", "Grant limitado a este Job.", evaluated.workflow)
        if evaluated.decision == "deny":
            self.jobs.fail_job(job_id, "policy_denied")
            raise RuntimeError("policy_denied")
        report = {
            "job_id": job_id,
            "branch": branch,
            "target": operation["target"],
            "diff_hash": diff_hash,
            "changed_paths": context["paths"],
            "diff_state": "modified" if context["paths"] else "clean",
            "decision": evaluated.decision,
            "policy_reason": evaluated.reason,
            "commit_message": commit_message,
            "risks": [
                f"{item['severity']}: {item['title']} ({item['file']})"
                for item in (self.jobs.get_job(job_id) or {}).get("findings", [])
                if item.get("triage_decision") != "reject"
            ],
        }
        self._write_report(job_id, report)
        self.jobs.record_job_event(
            job_id,
            "final_review.created",
            "core",
            None,
            {**report, "artifact": f"jobs/{job_id}/final-review.md"},
        )
        approval = self.approvals.request(
            job_id,
            operation,
            diff_hash,
            idempotency_key=f"delivery:{job_id}:{diff_hash}",
        )
        self.jobs.record_job_event(job_id, "approval.requested", "core", None, approval)
        if evaluated.decision == "allow":
            self.approvals.decide(
                str(approval["id"]),
                decision="approve",
                scope="once",
                reason="Política allow.",
                idempotency_key=f"delivery-auto:{job_id}:{diff_hash}",
            )
        return approval

    def _write_report(self, job_id: str, report: dict[str, Any]) -> None:
        report_path = self.output_root / "jobs" / job_id / "final-review.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_text = (
            "# Revisión final\n\n"
            + "\n".join(
                f"- **{key}:** {json.dumps(value, ensure_ascii=False)}" for key, value in report.items()
            )
            + "\n"
        )
        report_path.write_text(redact_text(report_text), encoding="utf-8")

    def deliver(self, job_id: str) -> str:
        context = self.jobs.delivery_context(job_id)
        if context is None:
            raise RuntimeError("delivery_context_missing")
        branch = str(context["branch"])
        diff_hash = self.git_delivery.diff_hash(str(context["diff"]))
        operation = self.approvals.approved_operation(job_id, diff_hash)
        if operation is None:
            raise RuntimeError("delivery_approval_missing")
        return self.git_delivery.deliver(
            job_id=job_id,
            job_number=int(context["number"]),
            worktree=Path(str(context["worktree_path"])),
            expected_branch=branch,
            message=str(operation["message"]),
            diff_hash=diff_hash,
            operation=operation,
        )
