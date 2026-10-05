from __future__ import annotations

import fnmatch
import hashlib
import json
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from relayforge.core.ids import new_ulid
from relayforge.core.states import JobStatus, validate_transition
from relayforge.db.models import Approval, ApprovalGrant, Event, Job, utc_now


class ApprovalConflict(RuntimeError):
    pass


class ApprovalService:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    @staticmethod
    def digest(value: dict[str, Any]) -> str:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    def request(
        self,
        job_id: str,
        operation: dict[str, Any],
        diff_hash: str,
        idempotency_key: str,
        approval_kind: str = "delivery",
    ) -> dict[str, Any]:
        operation_hash = self.digest(operation)
        with self.sessions.begin() as session:
            existing = session.scalar(select(Approval).where(Approval.idempotency_key == idempotency_key))
            if existing is not None:
                if (
                    existing.job_id != job_id
                    or existing.operation_hash != operation_hash
                    or existing.diff_hash != diff_hash
                ):
                    raise ApprovalConflict("La clave de idempotencia ya representa otra operación.")
                return self._serialize(existing)
            job = session.get(Job, job_id)
            if job is None:
                raise LookupError(job_id)
            approval = Approval(
                id=new_ulid(),
                job_id=job_id,
                operation_json=json.dumps(operation, sort_keys=True, separators=(",", ":")),
                operation_hash=operation_hash,
                diff_hash=diff_hash,
                status="pending",
                idempotency_key=idempotency_key,
                created_at=utc_now(),
            )
            session.add(approval)
            if approval_kind not in {"delivery", "plan"}:
                raise ValueError("Tipo de aprobación inválido.")
            job.approval_kind = approval_kind
            if job.status != JobStatus.WAITING_APPROVAL.value:
                old_status, new_status = validate_transition(job.status, JobStatus.WAITING_APPROVAL)
                job.status = JobStatus.WAITING_APPROVAL.value
                job.updated_at = utc_now()
                job.version += 1
                self._state_event(session, job, old_status.value, new_status.value, job.updated_at)
            return self._serialize(approval)

    def list_pending(self) -> list[dict[str, Any]]:
        with self.sessions() as session:
            rows = session.scalars(
                select(Approval).where(Approval.status == "pending").order_by(Approval.created_at)
            ).all()
            results = []
            for row in rows:
                item = self._serialize(row)
                operation = json.loads(row.operation_json)
                job = session.get(Job, row.job_id)
                overlaps: list[dict[str, Any]] = []
                if job is not None and job.repository_id is not None:
                    paths = set(operation.get("paths", []))
                    peers = session.scalars(
                        select(Job).where(
                            Job.repository_id == job.repository_id,
                            Job.id != job.id,
                            Job.status.not_in(
                                [JobStatus.COMPLETED.value, JobStatus.FAILED.value, JobStatus.CANCELLED.value]
                            ),
                        )
                    ).all()
                    for peer in peers:
                        peer_paths = set(json.loads(peer.diff_paths_json or "[]"))
                        shared = sorted(paths & peer_paths)
                        if shared:
                            overlaps.append({"job_id": peer.id, "paths": shared})
                item["overlaps"] = overlaps
                results.append(item)
            return results

    def decide(
        self,
        approval_id: str,
        *,
        decision: str,
        scope: str,
        reason: str | None,
        idempotency_key: str,
        policy_decision: str = "ask",
    ) -> dict[str, Any]:
        if decision not in {"approve", "reject"} or scope not in {"once", "job"}:
            raise ValueError("Decisión o alcance inválido.")
        with self.sessions.begin() as session:
            prior = session.scalar(
                select(Approval).where(Approval.decision_idempotency_key == idempotency_key)
            )
            if prior is not None:
                if prior.id != approval_id or prior.decision != decision or prior.scope != scope:
                    raise ApprovalConflict("La clave de idempotencia ya se usó para otra decisión.")
                return self._serialize(prior)
            approval = session.get(Approval, approval_id)
            if approval is None:
                raise LookupError(approval_id)
            if approval.status != "pending":
                raise ApprovalConflict("La aprobación ya fue decidida.")
            if decision == "approve" and policy_decision == "deny":
                raise ApprovalConflict("Una operación denegada por política no se puede aprobar.")
            job = session.get(Job, approval.job_id)
            if job is None:
                raise LookupError(approval.job_id)
            approval.status = "decided"
            approval.decision = decision
            approval.decision_idempotency_key = idempotency_key
            approval.scope = scope
            approval.reason = (reason or "").strip() or None
            approval.decided_at = utc_now()
            job.updated_at = approval.decided_at
            if decision == "reject":
                old_status, new_status = validate_transition(job.status, JobStatus.FAILED)
                job.status = JobStatus.FAILED.value
                job.finished_at = approval.decided_at
                job.error_code = "approval_rejected"
                job.error_message = approval.reason or "La aprobación fue rechazada."
                job.version += 1
                self._state_event(session, job, old_status.value, new_status.value, approval.decided_at)
            elif scope == "job":
                operation = json.loads(approval.operation_json)
                session.add(
                    ApprovalGrant(
                        id=new_ulid(),
                        approval_id=approval.id,
                        job_id=approval.job_id,
                        matcher_json=json.dumps(operation, sort_keys=True, separators=(",", ":")),
                        created_at=approval.decided_at,
                    )
                )
            return self._serialize(approval)

    def is_approved(self, job_id: str, operation: dict[str, Any], diff_hash: str) -> bool:
        digest = self.digest(operation)
        with self.sessions() as session:
            exact = session.scalar(
                select(Approval).where(
                    Approval.job_id == job_id,
                    Approval.operation_hash == digest,
                    Approval.diff_hash == diff_hash,
                    Approval.decision == "approve",
                    Approval.status == "decided",
                )
            )
            return exact is not None

    def approved_operation(self, job_id: str, diff_hash: str) -> dict[str, Any] | None:
        with self.sessions() as session:
            row = session.scalar(
                select(Approval).where(
                    Approval.job_id == job_id,
                    Approval.diff_hash == diff_hash,
                    Approval.decision == "approve",
                    Approval.status == "decided",
                )
            )
            return json.loads(row.operation_json) if row is not None else None

    def grant_allows(self, job_id: str, operation: dict[str, Any]) -> bool:
        with self.sessions() as session:
            grants = session.scalars(select(ApprovalGrant).where(ApprovalGrant.job_id == job_id)).all()
            for grant in grants:
                matcher = json.loads(grant.matcher_json)
                if not isinstance(matcher, dict):
                    continue
                matched = True
                for key, expected in matcher.items():
                    actual = operation.get(key)
                    if key == "paths":
                        matched = actual == expected
                    elif isinstance(expected, str) and isinstance(actual, str):
                        matched = fnmatch.fnmatchcase(actual.casefold(), expected.casefold())
                    else:
                        matched = actual == expected
                    if not matched:
                        break
                if matched:
                    return True
            return False

    @staticmethod
    def _state_event(session: Session, job: Job, old: str, new: str, now: str) -> None:
        seq = (
            session.scalar(select(func.max(Event.seq)).where(Event.conversation_id == job.conversation_id))
            or 0
        ) + 1
        session.add(
            Event(
                conversation_id=job.conversation_id,
                seq=seq,
                ts=now,
                type="job.state_changed",
                actor="core",
                job_id=job.id,
                step_id=None,
                payload_json=json.dumps({"data": {"from": old, "to": new}}, separators=(",", ":")),
            )
        )

    @staticmethod
    def _serialize(row: Approval) -> dict[str, Any]:
        return {
            "id": row.id,
            "job_id": row.job_id,
            "operation": json.loads(row.operation_json),
            "operation_hash": row.operation_hash,
            "diff_hash": row.diff_hash,
            "status": row.status,
            "decision": row.decision,
            "scope": row.scope,
            "reason": row.reason,
            "created_at": row.created_at,
            "decided_at": row.decided_at,
        }
