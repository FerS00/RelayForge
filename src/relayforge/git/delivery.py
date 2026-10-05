from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path

from relayforge.core.approvals import ApprovalService
from relayforge.git.operations import git

GitCommand = Callable[..., str]


class DeliveryError(RuntimeError):
    pass


class GitDelivery:
    def __init__(self, approvals: ApprovalService, git_command: GitCommand = git) -> None:
        self.approvals = approvals
        self.git = git_command

    @staticmethod
    def diff_hash(patch: str) -> str:
        return hashlib.sha256(patch.encode("utf-8")).hexdigest()

    @staticmethod
    def remote_fingerprint(remote_url: str) -> str:
        return hashlib.sha256(remote_url.encode("utf-8")).hexdigest()

    def deliver(
        self,
        *,
        job_id: str,
        job_number: int,
        worktree: Path,
        expected_branch: str,
        message: str,
        diff_hash: str,
        operation: dict[str, object],
    ) -> str:
        if operation.get("operation") in {"git.merge", "git.force_push", "git.push_protected_branch"}:
            raise DeliveryError("La operación está denegada.")
        expected = f"agent/job-{job_number}"
        if expected_branch != expected or expected_branch.casefold() in {"main", "master", "release"}:
            raise DeliveryError("La rama destino no está permitida.")
        if operation.get("branch") != expected_branch or operation.get("remote") != "origin":
            raise DeliveryError("La operación no coincide con la aprobación.")
        current_branch = self.git(worktree, "symbolic-ref", "--quiet", "--short", "HEAD")
        if current_branch != expected_branch:
            raise DeliveryError("La rama del worktree cambió después de la aprobación.")
        self.git(worktree, "add", "-N", "--", ".")
        current_patch = self.git(worktree, "diff", "--no-ext-diff", "--no-color", "HEAD", timeout=60)
        if self.diff_hash(current_patch) != diff_hash:
            raise DeliveryError("El diff cambió después de la aprobación.")
        self.git(worktree, "add", "--all")
        staged_patch = self.git(
            worktree, "diff", "--cached", "--no-ext-diff", "--no-color", "HEAD", timeout=60
        )
        if self.diff_hash(staged_patch) != diff_hash:
            raise DeliveryError("El diff preparado para commit no coincide con el aprobado.")
        if not self.approvals.is_approved(job_id, operation, diff_hash):
            raise DeliveryError("No hay aprobación vigente para esta operación exacta.")
        remote_url = self.git(worktree, "remote", "get-url", "origin")
        if operation.get("remote_fingerprint") != self.remote_fingerprint(remote_url):
            raise DeliveryError("El remoto cambió después de la aprobación.")
        self.git(worktree, "commit", "-m", message)
        commit_sha = self.git(worktree, "rev-parse", "HEAD")
        self.git(worktree, "push", "origin", f"HEAD:refs/heads/{expected_branch}", timeout=120)
        return commit_sha
