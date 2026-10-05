from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session, sessionmaker

from relayforge.adapters.base import (
    AuditResult,
    ConversationContext,
    NormalizedEvent,
    OrchestratorAdapter,
    PlannerAdapter,
    PlanResult,
    TriageResult,
)
from relayforge.core.events import EventBus
from relayforge.core.ids import new_ulid
from relayforge.core.states import ACTIVE_STATES, JobStatus, validate_transition
from relayforge.db.models import Conversation, Event, Finding, Job, JobStep, Repository, utc_now
from relayforge.security.redact import redact_text


class JobNotFound(LookupError):
    pass


class VersionConflict(RuntimeError):
    pass


def _next_seq(session: Session, conversation_id: str) -> int:
    return (
        session.scalar(select(func.max(Event.seq)).where(Event.conversation_id == conversation_id)) or 0
    ) + 1


class JobService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        event_bus: EventBus,
        orchestrator: OrchestratorAdapter,
        workspace_dir: Path,
        output_root: Path,
    ) -> None:
        self.sessions = sessions
        self.event_bus = event_bus
        self.orchestrator = orchestrator
        self.workspace_dir = workspace_dir
        self.output_root = output_root
        self.planners: dict[str, PlannerAdapter] = {"claude": orchestrator}

    def planner_for(self, job: dict[str, Any]) -> PlannerAdapter:
        planner = self.planners.get(str(job.get("planning_agent", "claude")))
        if planner is None:
            raise RuntimeError("planner_unavailable")
        return planner

    def record_usage(self, step_id: str, agent: str, usage: dict[str, int]) -> None:
        with self.sessions() as session:
            step = session.get(JobStep, step_id)
            job_id = step.job_id if step else None
        if job_id:
            self.record_job_event(job_id, "agent.usage", agent, step_id, usage)

    def record_turn(self, step_id: str, agent: str) -> None:
        with self.sessions() as session:
            step = session.get(JobStep, step_id)
            job_id = step.job_id if step else None
        if job_id:
            self.record_job_event(job_id, "agent.turn_started", agent, step_id, {})

    def pause_for_agent(self, job_id: str, code: str, stage: str) -> None:
        with self.sessions.begin() as session:
            row = session.get(Job, job_id)
            if row is None:
                raise JobNotFound(job_id)
            row.paused_stage = stage
            row.error_code = code
            row.error_message = (
                "El agente alcanzó su límite de uso. Selecciona un agente/modelo disponible para continuar."
                if code == "rate_limited"
                else "El agente requiere iniciar sesión. Autentícalo o selecciona un agente disponible."
            )
        self.transition(job_id, JobStatus.WAITING_AGENT, details={"stage": stage, "error_code": code})

    def dispatch_step(
        self, job_id: str, agent: str | None, model: str | None, version: int
    ) -> dict[str, Any]:
        with self.sessions.begin() as session:
            row = session.get(Job, job_id)
            if row is None:
                raise JobNotFound(job_id)
            if row.version != version:
                raise VersionConflict("job_version_conflict")
            approval = row.status == JobStatus.WAITING_APPROVAL.value and row.approval_kind == "plan"
            if not approval and row.status not in {
                JobStatus.WAITING_AGENT.value,
                JobStatus.INTERRUPTED.value,
                JobStatus.WAITING_RETRY.value,
            }:
                raise ValueError("job_not_dispatchable")
            stage = row.paused_stage
            if approval:
                stage = "audit" if agent == "antigravity" else "implement"
            if stage is None:
                interrupted = session.scalar(
                    select(JobStep)
                    .where(JobStep.job_id == job_id, JobStep.status.in_(["FAILED", "INTERRUPTED"]))
                    .order_by(JobStep.finished_at.desc(), JobStep.id.desc())
                )
                stage = interrupted.kind if interrupted else "plan"
            allowed = {
                "plan": {"claude", "codex"},
                "triage": {"claude", "codex"},
                "implement": {"codex"},
                "audit": {"antigravity"},
            }
            selected = agent or (
                row.planning_agent
                if stage in {"plan", "triage"}
                else "codex"
                if stage == "implement"
                else "antigravity"
            )
            if selected not in allowed.get(stage, set()):
                raise ValueError("agent_role_mismatch")
            old_agent = row.planning_agent if stage in {"plan", "triage"} else selected
            old_status, old_error = row.status, row.error_code
            target = (
                old_status
                if approval
                else {
                    "plan": JobStatus.QUEUED.value,
                    "triage": JobStatus.TRIAGING.value,
                    "implement": JobStatus.IMPLEMENTING.value,
                    "audit": JobStatus.AUDITING.value,
                }[stage]
            )
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.version == version, Job.status == old_status)
                    .values(version=version + 1)
                ),
            )
            if result.rowcount != 1:
                raise VersionConflict("job_version_conflict")
            if stage in {"plan", "triage"}:
                row.planning_agent, row.planning_model = selected, model
                if selected != old_agent:
                    conversation = session.get(Conversation, row.conversation_id)
                    if conversation is not None:
                        conversation.session_id = new_ulid()
                        conversation.session_established = 0
                        conversation.orchestrator = selected
                        row.orchestrator_session_id = conversation.session_id
            elif stage == "implement":
                row.implementation_model = model
            else:
                row.audit_model = model
            row.status = target
            row.updated_at = utc_now()
            if not approval:
                row.paused_stage = row.retry_at = row.error_code = row.error_message = row.finished_at = None
                step = session.scalar(
                    select(JobStep)
                    .where(JobStep.job_id == job_id, JobStep.kind == stage)
                    .order_by(JobStep.id.desc())
                )
                if step is not None and stage in {"plan", "implement"} and step.status != "SUCCEEDED":
                    step.status, step.agent = "PENDING", selected
                    step.attempt += 1
                    step.finished_at = step.pid = step.pid_create_time = None
                    step.error_code = None
        self.record_job_event(
            job_id,
            "agent.selected",
            "core",
            None,
            {
                "stage": stage,
                "from_agent": old_agent,
                "agent": selected,
                "model": model,
                "reason": old_error,
                "from_status": old_status,
                "to_status": target,
            },
        )
        result_job = self.get_job(job_id)
        assert result_job is not None
        return result_job

    def create_job(
        self,
        title: str | None,
        request_text: str,
        idempotency_key: str,
        repository_id: str | None = None,
        workflow: str = "auto",
        planning_agent: str = "claude",
        planning_model: str | None = None,
        implementation_model: str | None = None,
        audit_model: str | None = None,
        require_plan_approval: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        request_text = redact_text(request_text)
        title = redact_text(title) if title else None
        now, job_id, conversation_id = utc_now(), new_ulid(), new_ulid()
        with self.sessions.begin() as session:
            existing = session.scalar(select(Job).where(Job.idempotency_key == idempotency_key))
            if existing is not None:
                return self._serialize(session, existing), False
            repository = session.get(Repository, repository_id) if repository_id else None
            if repository_id and (repository is None or not repository.enabled):
                raise ValueError("El repositorio no existe o está deshabilitado.")
            conversation = Conversation(
                id=conversation_id,
                title=title or " ".join(request_text.split())[:60] or "Nueva tarea",
                workspace_dir=repository.path if repository else str(self.workspace_dir),
                orchestrator=planning_agent,
                session_id=new_ulid(),
                session_established=0,
                created_at=now,
                updated_at=now,
            )
            session.add(conversation)
            session.flush()
            next_number = (session.scalar(select(func.max(Job.number))) or 0) + 1
            job = Job(
                id=job_id,
                number=next_number,
                title=conversation.title,
                request_text=request_text,
                workflow=workflow if repository_id else "plan",
                planning_agent=planning_agent,
                planning_model=planning_model,
                implementation_model=implementation_model,
                audit_model=audit_model,
                require_plan_approval=int(require_plan_approval),
                status=JobStatus.QUEUED.value,
                conversation_id=conversation_id,
                repository_id=repository.id if repository else None,
                iteration=1,
                max_iterations=3,
                orchestrator_session_id=conversation.session_id,
                created_at=now,
                updated_at=now,
                version=0,
                idempotency_key=idempotency_key,
            )
            step = JobStep(
                id=new_ulid(),
                job_id=job_id,
                kind="plan",
                agent=planning_agent,
                iteration=1,
                status="PENDING",
                resumable=0,
                attempt=1,
            )
            session.add_all([job, step])
            session.flush()
            event = Event(
                conversation_id=conversation_id,
                seq=1,
                ts=now,
                type="job.state_changed",
                actor="core",
                job_id=job_id,
                step_id=None,
                payload_json=json.dumps(
                    {"data": {"from": None, "to": JobStatus.QUEUED.value}}, separators=(",", ":")
                ),
            )
            session.add(event)
            result = self._serialize(session, job)
        self.event_bus.publish(
            conversation_id,
            NormalizedEvent(
                "job.state_changed",
                "core",
                None,
                {"from": None, "to": JobStatus.QUEUED.value, "_seq": 1},
                now,
            ),
        )
        return result, True

    def list_jobs(self, repository_id: str | None = None) -> list[dict[str, Any]]:
        with self.sessions() as session:
            query = select(Job).order_by(Job.updated_at.desc(), Job.number.desc())
            if repository_id is not None:
                query = query.where(Job.repository_id == repository_id)
            rows = session.scalars(query).all()
            return [self._serialize(session, row, include_steps=False) for row in rows]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.sessions() as session:
            job = session.get(Job, job_id)
            return self._serialize(session, job) if job is not None else None

    def get_job_conversation(self, job_id: str) -> str | None:
        with self.sessions() as session:
            job = session.get(Job, job_id)
            return job.conversation_id if job else None

    def get_events(self, job_id: str, after_seq: int) -> tuple[str | None, list[NormalizedEvent]]:
        with self.sessions() as session:
            job = session.get(Job, job_id)
            if job is None:
                return None, []
            rows = session.scalars(
                select(Event).where(Event.job_id == job_id, Event.seq > after_seq).order_by(Event.seq)
            ).all()
            events: list[NormalizedEvent] = []
            for row in rows:
                payload = json.loads(row.payload_json)
                data = payload.get("data", {}) if isinstance(payload, dict) else {}
                if not isinstance(data, dict):
                    data = {}
                events.append(
                    NormalizedEvent(
                        row.type,
                        row.actor,
                        row.step_id,
                        {**data, "_seq": row.seq},
                        row.ts,
                    )
                )
            return job.conversation_id, events

    def queued_job_ids(self) -> list[str]:
        with self.sessions() as session:
            return list(session.scalars(select(Job.id).where(Job.status == JobStatus.QUEUED.value)))

    def concurrency_key(self, job_id: str) -> str:
        with self.sessions() as session:
            job = session.get(Job, job_id)
            return job.repository_id if job and job.repository_id else "default-workspace"

    def running_step_kind(self, job_id: str) -> str:
        with self.sessions() as session:
            step = session.scalar(
                select(JobStep).where(JobStep.job_id == job_id, JobStep.status == "RUNNING")
            )
            return step.kind if step else "plan"

    def check_commands(self, job_id: str) -> list[dict[str, Any]]:
        with self.sessions() as session:
            job = session.get(Job, job_id)
            repository = session.get(Repository, job.repository_id) if job and job.repository_id else None
            if repository is None:
                return []
            value = json.loads(repository.check_commands_json or "[]")
            return value if isinstance(value, list) else []

    def delivery_context(self, job_id: str) -> dict[str, Any] | None:
        with self.sessions() as session:
            job = session.get(Job, job_id)
            repository = session.get(Repository, job.repository_id) if job and job.repository_id else None
            if job is None or repository is None or job.worktree_path is None or job.branch is None:
                return None
            return {
                "job_id": job.id,
                "number": job.number,
                "title": job.title,
                "workflow": job.workflow,
                "repository_id": repository.id,
                "repository_path": repository.path,
                "profile": repository.policy_profile,
                "default_branch": repository.default_branch,
                "branch": job.branch,
                "worktree_path": job.worktree_path,
                "diff": job.diff_text or "",
                "paths": json.loads(job.diff_paths_json or "[]"),
                "status": job.status,
            }

    def audit_context(self, job_id: str, iteration: int) -> tuple[ConversationContext, str, dict[str, Any]]:
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            if job is None or job.worktree_path is None:
                raise RuntimeError("audit_worktree_missing")
            conversation = session.get(Conversation, job.conversation_id)
            if conversation is None:
                raise RuntimeError("job_relations_missing")
            step = JobStep(
                id=new_ulid(),
                job_id=job_id,
                kind="audit",
                agent="antigravity",
                iteration=iteration,
                status="RUNNING",
                resumable=0,
                attempt=1,
                started_at=utc_now(),
            )
            session.add(step)
            session.flush()
            context = ConversationContext(
                conversation.id,
                conversation.session_id,
                bool(conversation.session_established),
                Path(job.worktree_path),
                step.id,
            )
            return (
                context,
                step.id,
                {
                    "worktree": job.worktree_path,
                    "paths": json.loads(job.diff_paths_json or "[]"),
                    "diff": job.diff_text or "",
                    "thread_id": job.codex_thread_id,
                    "iteration": iteration,
                    "max_iterations": job.max_iterations,
                },
            )

    def triage_context(self, job_id: str, iteration: int) -> ConversationContext:
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            conversation = session.get(Conversation, job.conversation_id) if job else None
            if job is None or conversation is None or job.worktree_path is None:
                raise RuntimeError("triage_context_missing")
            step = JobStep(
                id=new_ulid(),
                job_id=job_id,
                kind="triage",
                agent=job.planning_agent,
                iteration=iteration,
                status="RUNNING",
                started_at=utc_now(),
            )
            session.add(step)
            session.flush()
            return ConversationContext(
                conversation.id,
                conversation.session_id,
                bool(conversation.session_established),
                Path(job.worktree_path),
                step.id,
                job.planning_model or "",
            )

    def finish_triage_step(self, context: ConversationContext, status: str = "SUCCEEDED") -> None:
        with self.sessions.begin() as session:
            step = session.get(JobStep, context.step_id)
            if step is not None:
                step.status = status
                step.finished_at = utc_now()

    def increment_iteration(self, job_id: str) -> int:
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise JobNotFound(job_id)
            if job.iteration >= job.max_iterations:
                raise RuntimeError("iteration_limit")
            job.iteration += 1
            return job.iteration

    def set_approval_kind(self, job_id: str, kind: str | None) -> None:
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise JobNotFound(job_id)
            job.approval_kind = kind

    def set_workflow(self, job_id: str, workflow: str, max_iterations: int) -> None:
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise JobNotFound(job_id)
            job.workflow = workflow
            job.max_iterations = min(job.max_iterations, max_iterations)
            job.updated_at = utc_now()

    def mark_findings_fixed(self, job_id: str, finding_ids: list[str], iteration: int) -> None:
        with self.sessions.begin() as session:
            for finding_id in finding_ids:
                finding = session.get(Finding, finding_id)
                if finding is not None and finding.job_id == job_id:
                    finding.fixed_in_iteration = iteration

    def record_audit(
        self, job_id: str, step_id: str, iteration: int, result: AuditResult
    ) -> list[dict[str, Any]]:
        now = utc_now()
        records: list[dict[str, Any]] = []
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            step = session.get(JobStep, step_id)
            if job is None or step is None or step.kind != "audit":
                raise RuntimeError("audit_step_missing")
            step.status = "SUCCEEDED" if result.verdict != "BLOCKED" else "FAILED"
            step.finished_at = now
            step.error_code = "audit_blocked" if result.verdict == "BLOCKED" else None
            step.summary_json = json.dumps(
                {
                    "verdict": result.verdict,
                    "summary": result.summary,
                    "hashes_before": result.hashes_before,
                    "hashes_after": result.hashes_after,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            for item in result.findings:
                finding = Finding(
                    id=new_ulid(),
                    job_id=job_id,
                    audit_step_id=step_id,
                    audit_no=iteration,
                    external_id=item.external_id,
                    severity=item.severity,
                    file=item.file,
                    line=item.line,
                    title=item.title,
                    evidence=item.evidence,
                    recommendation=item.recommendation,
                )
                session.add(finding)
                records.append(
                    {
                        "id": finding.id,
                        "external_id": item.external_id,
                        "severity": item.severity,
                        "file": item.file,
                        "line": item.line,
                        "title": item.title,
                        "evidence": item.evidence,
                        "recommendation": item.recommendation,
                    }
                )
            session.flush()
        self.record_job_event(
            job_id,
            "audit.result",
            "antigravity",
            step_id,
            {
                "verdict": result.verdict,
                "summary": result.summary,
                "findings": len(records),
                "iteration": iteration,
            },
        )
        return records

    def record_triage(
        self, job_id: str, findings: list[dict[str, Any]], result: TriageResult
    ) -> list[dict[str, Any]]:
        decisions = {item.finding_id: item for item in result.decisions}
        if set(decisions) != {str(item["id"]) for item in findings}:
            raise ValueError("triage_coverage_invalid")
        with self.sessions.begin() as session:
            for item in findings:
                decision = decisions[str(item["id"])]
                finding = session.get(Finding, str(item["id"]))
                if finding is None or finding.job_id != job_id or not decision.reason.strip():
                    raise ValueError("triage_finding_invalid")
                finding.triage_decision = decision.decision
                finding.triage_reason = decision.reason
        for item in findings:
            decision = decisions[str(item["id"])]
            self.record_job_event(
                job_id,
                "triage.decision",
                str((self.get_job(job_id) or {}).get("planning_agent", "claude")),
                None,
                {"finding_id": item["id"], "decision": decision.decision, "reason": decision.reason},
            )
        return [item for item in findings if decisions[str(item["id"])].decision == "accept"]

    def start_checks(self, job_id: str) -> str:
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise JobNotFound(job_id)
            step = session.scalar(select(JobStep).where(JobStep.job_id == job_id, JobStep.kind == "checks"))
            if step is None:
                step = JobStep(id=new_ulid(), job_id=job_id, kind="checks", agent="core", status="RUNNING")
                session.add(step)
            step.status = "RUNNING"
            step.started_at = utc_now()
            step.finished_at = None
            step.pid = None
            step.pid_create_time = None
            step.heartbeat_at = utc_now()
            return step.id

    def finish_checks(self, job_id: str, step_id: str, results: list[dict[str, Any]]) -> None:
        now = utc_now()
        all_passed = all(result.get("status") == "passed" for result in results)
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            step = session.get(JobStep, step_id)
            if job is None or step is None or step.kind != "checks":
                raise RuntimeError("checks_step_missing")
            timed_out = any(result.get("status") == "timeout" for result in results)
            step.status = "SUCCEEDED" if all_passed else "TIMED_OUT" if timed_out else "FAILED"
            step.finished_at = now
            step.error_code = (
                None
                if all_passed
                else next(
                    (str(item.get("status")) for item in results if item.get("status") != "passed"), "failed"
                )
            )
            step.exit_code = next((item.get("exit_code") for item in reversed(results)), None)
            step.summary_json = json.dumps({"results": results}, ensure_ascii=False, separators=(",", ":"))
            conversation_id = job.conversation_id
            events: list[NormalizedEvent] = []
            for result in results:
                seq = _next_seq(session, conversation_id)
                database_event = Event(
                    conversation_id=conversation_id,
                    seq=seq,
                    ts=now,
                    type="checks.result",
                    actor="checks",
                    job_id=job_id,
                    step_id=step_id,
                    payload_json=json.dumps({"data": result}, ensure_ascii=False, separators=(",", ":")),
                )
                session.add(database_event)
                events.append(
                    NormalizedEvent("checks.result", "checks", step_id, {**result, "_seq": seq}, now)
                )
        for published_event in events:
            self.event_bus.publish(conversation_id, published_event)

    def planning_context(self, job_id: str) -> tuple[ConversationContext, str] | None:
        with self.sessions() as session:
            job = session.get(Job, job_id)
            if job is None:
                return None
            conversation = session.get(Conversation, job.conversation_id)
            step = session.scalar(select(JobStep).where(JobStep.job_id == job_id, JobStep.kind == "plan"))
            if conversation is None or step is None:
                raise RuntimeError("job_relations_missing")
            return (
                ConversationContext(
                    conversation_id=conversation.id,
                    session_id=conversation.session_id,
                    session_established=bool(conversation.session_established),
                    cwd=Path(job.worktree_path or conversation.workspace_dir),
                    step_id=step.id,
                    model=job.planning_model or "",
                ),
                step.id,
            )

    def transition(
        self,
        job_id: str,
        target: JobStatus,
        *,
        expected_version: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise JobNotFound(job_id)
            if expected_version is not None and job.version != expected_version:
                raise VersionConflict("La versión del Job cambió.")
            source, target_state = validate_transition(job.status, target)
            now = utc_now()
            new_version = job.version + 1
            result = cast(
                CursorResult[Any],
                session.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.status == source.value, Job.version == job.version)
                    .values(
                        status=target_state.value,
                        version=new_version,
                        updated_at=now,
                        finished_at=(
                            now
                            if target_state in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
                            else job.finished_at
                        ),
                    )
                    .execution_options(synchronize_session=False)
                ),
            )
            if result.rowcount != 1:
                raise VersionConflict("La versión del Job cambió.")
            session.refresh(job)
            payload = {"from": source.value, "to": target_state.value, **(details or {})}
            seq = _next_seq(session, job.conversation_id)
            event = Event(
                conversation_id=job.conversation_id,
                seq=seq,
                ts=now,
                type="job.state_changed",
                actor="core",
                job_id=job.id,
                step_id=None,
                payload_json=json.dumps({"data": payload}, ensure_ascii=False, separators=(",", ":")),
            )
            session.add(event)
            serialized = self._serialize(session, job)
            conversation_id = job.conversation_id
        self.event_bus.publish(
            conversation_id,
            NormalizedEvent("job.state_changed", "core", None, {**payload, "_seq": seq}, now),
        )
        return serialized

    def set_step(
        self,
        job_id: str,
        status: str,
        *,
        started_at: str | None = None,
        finished_at: str | None = None,
        summary: PlanResult | None = None,
        error_code: str | None = None,
        kind: str = "plan",
    ) -> None:
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise JobNotFound(job_id)
            step = session.scalar(select(JobStep).where(JobStep.job_id == job_id, JobStep.kind == kind))
            if step is None:
                raise RuntimeError(f"{kind}_step_missing")
            step.status = status
            if status == "RUNNING":
                step.finished_at = None
                step.error_code = None
                step.pid = None
                step.pid_create_time = None
            if started_at is not None:
                step.started_at = started_at
            if finished_at is not None:
                step.finished_at = finished_at
            if summary is not None:
                step.summary_json = json.dumps(
                    {
                        "objective": summary.objective,
                        "summary": summary.summary,
                        "steps": list(summary.steps),
                        "risks": list(summary.risks),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            if error_code is not None:
                step.error_code = error_code

    def update_step_runtime(
        self, job_id: str, kind: str, *, pid: int | None = None, pid_create_time: float | None = None
    ) -> None:
        with self.sessions.begin() as session:
            step = session.scalar(select(JobStep).where(JobStep.job_id == job_id, JobStep.kind == kind))
            if step is None:
                return
            step.pid = pid
            step.pid_create_time = pid_create_time
            step.heartbeat_at = utc_now()

    def heartbeat(self, job_id: str, kind: str) -> None:
        with self.sessions.begin() as session:
            step = session.scalar(select(JobStep).where(JobStep.job_id == job_id, JobStep.kind == kind))
            if step is not None and step.status == "RUNNING":
                step.heartbeat_at = utc_now()

    def update_step_by_id(
        self, step_id: str, *, pid: int | None = None, pid_create_time: float | None = None
    ) -> None:
        with self.sessions.begin() as session:
            step = session.get(JobStep, step_id)
            if step is not None:
                step.pid = pid
                step.pid_create_time = pid_create_time
                step.heartbeat_at = utc_now()

    def heartbeat_step(self, step_id: str) -> None:
        with self.sessions.begin() as session:
            step = session.get(JobStep, step_id)
            if step is not None and step.status == "RUNNING":
                step.heartbeat_at = utc_now()

    def schedule_retry(self, job_id: str, retry_at: str, error_code: str) -> bool:
        job = self.get_job(job_id)
        if job is None or int(job.get("retry_count", 0)) >= 1:
            return False
        with self.sessions.begin() as session:
            row = session.get(Job, job_id)
            if row is None or JobStatus(row.status) not in ACTIVE_STATES:
                return False
            row.retry_at = retry_at
            row.retry_count += 1
            row.paused_stage = {
                "IMPLEMENTING": "implement",
                "AUDITING": "audit",
                "TRIAGING": "triage",
                "TESTING": "checks",
            }.get(row.status, "plan")
        self.set_running_step_error(job_id, error_code)
        self.transition(
            job_id, JobStatus.WAITING_RETRY, details={"retry_at": retry_at, "error_code": error_code}
        )
        return True

    def set_running_step_error(self, job_id: str, error_code: str) -> None:
        with self.sessions.begin() as session:
            step = session.scalar(
                select(JobStep).where(JobStep.job_id == job_id, JobStep.status == "RUNNING")
            )
            if step is not None:
                step.status = "FAILED"
                step.error_code = error_code
                step.finished_at = utc_now()
                step.pid = None
                step.pid_create_time = None

    def retry_job_ids(self, now: str | None = None) -> list[str]:
        cutoff = now or utc_now()
        with self.sessions() as session:
            return list(
                session.scalars(
                    select(Job.id).where(
                        Job.status == JobStatus.WAITING_RETRY.value,
                        Job.retry_at.is_not(None),
                        Job.retry_at <= cutoff,
                    )
                )
            )

    def requeue_retry(self, job_id: str) -> bool:
        with self.sessions.begin() as session:
            row = session.get(Job, job_id)
            if row is None or row.status != JobStatus.WAITING_RETRY.value:
                return False
            row.retry_at = None
            target = {
                "implement": JobStatus.IMPLEMENTING,
                "audit": JobStatus.AUDITING,
                "triage": JobStatus.TRIAGING,
                "checks": JobStatus.TESTING,
            }.get(row.paused_stage or "plan", JobStatus.QUEUED)
            row.paused_stage = None
        self.transition(job_id, target, details={"reason": "retry_due"})
        return True

    def resume_interrupted(self, job_id: str, mode: str) -> dict[str, Any]:
        with self.sessions.begin() as session:
            row = session.get(Job, job_id)
            if row is None:
                raise JobNotFound(job_id)
            if row.status != JobStatus.INTERRUPTED.value:
                raise ValueError("job_not_interrupted")
            active = session.scalar(
                select(JobStep).where(JobStep.job_id == job_id, JobStep.status == "INTERRUPTED")
            )
            if mode == "resume_session" and (active is None or not active.resume_token):
                raise ValueError("resume_token_missing")
            if active is not None:
                active.status = "PENDING"
                active.pid = None
                active.pid_create_time = None
                active.finished_at = None
            row.retry_at = None
            target = {
                "implement": JobStatus.IMPLEMENTING,
                "audit": JobStatus.AUDITING,
                "triage": JobStatus.TRIAGING,
                "checks": JobStatus.TESTING,
            }.get(active.kind if active else "plan", JobStatus.QUEUED)
        return self.transition(job_id, target, details={"reason": mode})

    def complete_plan(self, job_id: str, plan: PlanResult) -> None:
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise JobNotFound(job_id)
            step = session.scalar(select(JobStep).where(JobStep.job_id == job_id, JobStep.kind == "plan"))
            if step is None:
                raise RuntimeError("plan_step_missing")
            now = utc_now()
            step.status = "SUCCEEDED"
            step.finished_at = now
            step.summary_json = json.dumps(
                {
                    "objective": plan.objective,
                    "summary": plan.summary,
                    "steps": list(plan.steps),
                    "risks": list(plan.risks),
                    "suggested_workflow": plan.suggested_workflow,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            seq = _next_seq(session, job.conversation_id)
            event = Event(
                conversation_id=job.conversation_id,
                seq=seq,
                ts=now,
                type="job.plan",
                actor=step.agent,
                job_id=job_id,
                step_id=step.id,
                payload_json=json.dumps(
                    {"data": json.loads(step.summary_json)}, ensure_ascii=False, separators=(",", ":")
                ),
            )
            session.add(event)
            conversation_id = job.conversation_id
        self.event_bus.publish(
            conversation_id,
            NormalizedEvent(
                "job.plan",
                step.agent,
                step.id,
                {
                    "objective": plan.objective,
                    "summary": plan.summary,
                    "steps": list(plan.steps),
                    "risks": list(plan.risks),
                    "_seq": seq,
                },
                now,
            ),
        )

    def implementation_context(self, job_id: str) -> dict[str, Any] | None:
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            if job is None or job.repository_id is None:
                return None
            repository = session.get(Repository, job.repository_id)
            if repository is None:
                return None
            step = session.scalar(
                select(JobStep).where(
                    JobStep.job_id == job_id, JobStep.kind == "implement", JobStep.iteration == job.iteration
                )
            )
            if step is None:
                step = JobStep(
                    id=new_ulid(),
                    job_id=job_id,
                    kind="implement",
                    agent="codex",
                    iteration=job.iteration,
                    status="PENDING",
                    resumable=0,
                    attempt=1,
                )
                session.add(step)
                session.flush()
            return {
                "job_id": job.id,
                "number": job.number,
                "repository_id": repository.id,
                "repository_path": repository.path,
                "base_sha": job.base_sha,
                "worktree_path": job.worktree_path,
                "thread_id": job.codex_thread_id or step.resume_token,
                "step_id": step.id,
            }

    def set_worktree(
        self, job_id: str, *, base_sha: str, branch: str, path: Path, start_implementation: bool = True
    ) -> None:
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise JobNotFound(job_id)
            job.base_sha = base_sha
            job.branch = branch
            job.worktree_path = str(path)
            if not start_implementation:
                return
            step = session.scalar(
                select(JobStep).where(
                    JobStep.job_id == job_id, JobStep.kind == "implement", JobStep.iteration == job.iteration
                )
            )
            if step is None:
                raise RuntimeError("implementation_step_missing")
            step.status = "RUNNING"
            step.started_at = utc_now()
            step.finished_at = None
            step.error_code = None
            step.pid = None
            step.pid_create_time = None

    def record_job_event(
        self, job_id: str, event_type: str, actor: str, step_id: str | None, data: dict[str, Any]
    ) -> None:
        now = utc_now()
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            if event_type == "agent.thread" and isinstance(data.get("thread_id"), str):
                step = session.get(JobStep, step_id) if step_id else None
                if step is not None:
                    step.resume_token = str(data["thread_id"])
                    step.resumable = 1
            seq = _next_seq(session, job.conversation_id)
            session.add(
                Event(
                    conversation_id=job.conversation_id,
                    seq=seq,
                    ts=now,
                    type=event_type,
                    actor=actor,
                    job_id=job.id,
                    step_id=step_id,
                    payload_json=json.dumps({"data": data}, ensure_ascii=False, separators=(",", ":")),
                )
            )
            conversation_id = job.conversation_id
        self.event_bus.publish(
            conversation_id,
            NormalizedEvent(event_type, actor, step_id, {**data, "_seq": seq}, now),
        )

    def complete_implementation(
        self, job_id: str, *, thread_id: str, diff_text: str, diff_paths: list[str], summary: str
    ) -> None:
        now = utc_now()
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            if job is None:
                raise JobNotFound(job_id)
            step = session.scalar(
                select(JobStep).where(
                    JobStep.job_id == job_id, JobStep.kind == "implement", JobStep.iteration == job.iteration
                )
            )
            if step is None:
                raise RuntimeError("implementation_step_missing")
            job.codex_thread_id = thread_id
            job.diff_text = diff_text
            job.diff_paths_json = json.dumps(diff_paths, ensure_ascii=False)
            step.status = "SUCCEEDED"
            step.finished_at = now
            step.resume_token = thread_id
            step.summary_json = json.dumps({"summary": summary}, ensure_ascii=False)
            seq = _next_seq(session, job.conversation_id)
            data = {"thread_id": thread_id, "paths": diff_paths, "summary": summary}
            session.add(
                Event(
                    conversation_id=job.conversation_id,
                    seq=seq,
                    ts=now,
                    type="implementation.completed",
                    actor="codex",
                    job_id=job.id,
                    step_id=step.id,
                    payload_json=json.dumps({"data": data}, ensure_ascii=False, separators=(",", ":")),
                )
            )
            conversation_id = job.conversation_id
        self.event_bus.publish(
            conversation_id,
            NormalizedEvent("implementation.completed", "codex", step.id, {**data, "_seq": seq}, now),
        )

    def fail_job(self, job_id: str, code: str) -> None:
        with self.sessions.begin() as session:
            job = session.get(Job, job_id)
            if job is None or JobStatus(job.status) in {JobStatus.CANCELLED, JobStatus.COMPLETED}:
                return
            job.error_code = code
            job.error_message = "No se pudo completar el workflow."
            if job.status == JobStatus.CANCELLING.value:
                return
        self.transition(job_id, JobStatus.FAILED, details={"error_code": code})

    def reconcile_active_jobs(self) -> None:
        with self.sessions() as session:
            identifiers = list(
                session.scalars(
                    select(Job.id).where(Job.status.in_([state.value for state in ACTIVE_STATES]))
                )
            )
        for job_id in identifiers:
            job = self.get_job(job_id)
            if job is None:
                continue
            target = (
                JobStatus.CANCELLED if job["status"] == JobStatus.CANCELLING.value else JobStatus.INTERRUPTED
            )
            with self.sessions.begin() as session:
                step = session.scalar(
                    select(JobStep).where(JobStep.job_id == job_id, JobStep.status == "RUNNING")
                )
                if step is not None:
                    step.status = "CANCELLED" if target is JobStatus.CANCELLED else "INTERRUPTED"
                    step.finished_at = utc_now()
                    step.pid = None
                    step.pid_create_time = None
            if target is JobStatus.CANCELLED:
                self._finish_cancelling(job_id)
            else:
                self.transition(job_id, target, details={"reason": "backend_restart"})

    def active_process_identities(self) -> list[tuple[int, float]]:
        with self.sessions() as session:
            rows = session.execute(
                select(JobStep.pid, JobStep.pid_create_time).where(
                    JobStep.status == "RUNNING",
                    JobStep.pid.is_not(None),
                    JobStep.pid_create_time.is_not(None),
                )
            ).all()
            return [
                (int(pid), float(created)) for pid, created in rows if pid is not None and created is not None
            ]

    def mark_stalled_steps(self, timeout_seconds: int = 600) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=timeout_seconds)
        stalled: list[tuple[str, str]] = []
        with self.sessions.begin() as session:
            rows = session.scalars(
                select(JobStep).where(JobStep.status == "RUNNING", JobStep.heartbeat_at.is_not(None))
            ).all()
            for step in rows:
                try:
                    heartbeat = datetime.fromisoformat(str(step.heartbeat_at).replace("Z", "+00:00"))
                except ValueError:
                    continue
                if heartbeat < cutoff and step.error_code != "stalled":
                    step.error_code = "stalled"
                    stalled.append((step.job_id, step.id))
        for job_id, step_id in stalled:
            self.record_job_event(
                job_id, "step.stalled", "core", step_id, {"timeout_seconds": timeout_seconds}
            )
        return len(stalled)

    def _finish_cancelling(self, job_id: str) -> None:
        current = self.get_job(job_id)
        if current and current["status"] == JobStatus.CANCELLING.value:
            self.transition(job_id, JobStatus.CANCELLED)

    def _serialize(self, session: Session, job: Job, *, include_steps: bool = True) -> dict[str, Any]:
        steps = (
            session.scalars(
                select(JobStep).where(JobStep.job_id == job.id).order_by(JobStep.started_at, JobStep.id)
            ).all()
            if include_steps
            else []
        )
        plan: dict[str, Any] | None = None
        serialized_steps: list[dict[str, Any]] = []
        for step in steps:
            summary = json.loads(step.summary_json) if step.summary_json else None
            if step.kind == "plan":
                plan = summary
            serialized_steps.append(
                {
                    "id": step.id,
                    "kind": step.kind,
                    "agent": step.agent,
                    "status": step.status,
                    "iteration": step.iteration,
                    "attempt": step.attempt,
                    "started_at": step.started_at,
                    "finished_at": step.finished_at,
                    "summary": summary,
                    "error_code": step.error_code,
                    "exit_code": step.exit_code,
                    "pid": step.pid,
                    "heartbeat_at": step.heartbeat_at,
                    "resumable": bool(step.resumable),
                    "resume_token": step.resume_token,
                }
            )
        result: dict[str, Any] = {
            "id": job.id,
            "number": job.number,
            "display_id": f"JOB-{job.number:06d}",
            "title": job.title,
            "request_text": job.request_text,
            "workflow": job.workflow,
            "planning_agent": job.planning_agent,
            "planning_model": job.planning_model,
            "implementation_model": job.implementation_model,
            "audit_model": job.audit_model,
            "paused_stage": job.paused_stage,
            "require_plan_approval": bool(job.require_plan_approval),
            "status": job.status,
            "conversation_id": job.conversation_id,
            "repository_id": job.repository_id,
            "base_sha": job.base_sha,
            "branch": job.branch,
            "worktree_path": job.worktree_path,
            "codex_thread_id": job.codex_thread_id,
            "approval_kind": job.approval_kind,
            "iteration": job.iteration,
            "max_iterations": job.max_iterations,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "finished_at": job.finished_at,
            "version": job.version,
            "error_code": job.error_code,
            "error_message": job.error_message,
            "retry_at": job.retry_at,
            "retry_count": job.retry_count,
            "plan": plan,
        }
        if include_steps:
            result["diff"] = job.diff_text
            result["diff_paths"] = json.loads(job.diff_paths_json) if job.diff_paths_json else []
            result["steps"] = serialized_steps
            event_rows = session.scalars(
                select(Event).where(Event.job_id == job.id).order_by(Event.seq).limit(500)
            ).all()
            result["events"] = [
                {
                    "seq": row.seq,
                    "ts": row.ts,
                    "type": row.type,
                    "actor": row.actor,
                    "data": (json.loads(row.payload_json).get("data", {})),
                }
                for row in event_rows
            ]
            result["findings"] = [
                {
                    "id": row.id,
                    "audit_no": row.audit_no,
                    "external_id": row.external_id,
                    "severity": row.severity,
                    "file": row.file,
                    "line": row.line,
                    "title": row.title,
                    "evidence": row.evidence,
                    "recommendation": row.recommendation,
                    "triage_decision": row.triage_decision,
                    "triage_reason": row.triage_reason,
                    "fixed_in_iteration": row.fixed_in_iteration,
                }
                for row in session.scalars(
                    select(Finding).where(Finding.job_id == job.id).order_by(Finding.audit_no, Finding.id)
                ).all()
            ]
        return result
