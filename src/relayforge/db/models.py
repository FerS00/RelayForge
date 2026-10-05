from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from relayforge.db.redacted import RedactedText


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(RedactedText(), default="Nueva conversación")
    workspace_dir: Mapped[str] = mapped_column(Text)
    orchestrator: Mapped[str] = mapped_column(String, default="claude")
    session_id: Mapped[str] = mapped_column(String)
    session_established: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String, default=utc_now)
    updated_at: Mapped[str] = mapped_column(String, default=utc_now)
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    jobs: Mapped[list[Job]] = relationship(back_populates="conversation")


class Repository(Base):
    __tablename__ = "repositories"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True)
    path: Mapped[str] = mapped_column(Text, unique=True)
    default_branch: Mapped[str] = mapped_column(String)
    check_commands_json: Mapped[str] = mapped_column(Text, default="[]")
    policy_profile: Mapped[str] = mapped_column(String, default="default")
    created_at: Mapped[str] = mapped_column(String, default=utc_now)
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    jobs: Mapped[list[Job]] = relationship(back_populates="repository")


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(RedactedText())
    step_id: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="complete")
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    ts: Mapped[str] = mapped_column(String, default=utc_now)
    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    __table_args__ = (Index("uq_messages_idempotency", "conversation_id", "idempotency_key", unique=True),)


class Event(Base):
    __tablename__ = "events"
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True)
    step_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload_json: Mapped[str] = mapped_column(RedactedText(json_content=True))


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    number: Mapped[int] = mapped_column(Integer, unique=True)
    title: Mapped[str] = mapped_column(RedactedText())
    request_text: Mapped[str] = mapped_column(RedactedText())
    workflow: Mapped[str] = mapped_column(String, default="plan")
    planning_agent: Mapped[str] = mapped_column(String, default="claude")
    planning_model: Mapped[str | None] = mapped_column(String, nullable=True)
    implementation_model: Mapped[str | None] = mapped_column(String, nullable=True)
    audit_model: Mapped[str | None] = mapped_column(String, nullable=True)
    paused_stage: Mapped[str | None] = mapped_column(String, nullable=True)
    require_plan_approval: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="QUEUED", index=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), unique=True
    )
    repository_id: Mapped[str | None] = mapped_column(
        ForeignKey("repositories.id", ondelete="SET NULL"), nullable=True
    )
    approval_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    iteration: Mapped[int] = mapped_column(Integer, default=1)
    max_iterations: Mapped[int] = mapped_column(Integer, default=3)
    base_sha: Mapped[str | None] = mapped_column(String, nullable=True)
    branch: Mapped[str | None] = mapped_column(String, nullable=True)
    worktree_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    codex_thread_id: Mapped[str | None] = mapped_column(String, nullable=True)
    diff_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    diff_paths_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    orchestrator_session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, default=utc_now)
    updated_at: Mapped[str] = mapped_column(String, default=utc_now, index=True)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)
    retry_at: Mapped[str | None] = mapped_column(String, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(RedactedText(), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True)
    conversation: Mapped[Conversation] = relationship(back_populates="jobs")
    repository: Mapped[Repository | None] = relationship(back_populates="jobs")
    steps: Mapped[list[JobStep]] = relationship(back_populates="job", cascade="all, delete-orphan")
    __table_args__ = (
        Index("uq_jobs_idempotency", "idempotency_key", unique=True),
        Index("ix_jobs_conversation_updated", "conversation_id", "updated_at"),
    )


class JobStep(Base):
    __tablename__ = "job_steps"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String)
    agent: Mapped[str] = mapped_column(String)
    iteration: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String, default="PENDING")
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pid_create_time: Mapped[float | None] = mapped_column(nullable=True)
    started_at: Mapped[str | None] = mapped_column(String, nullable=True)
    heartbeat_at: Mapped[str | None] = mapped_column(String, nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    resume_token: Mapped[str | None] = mapped_column(String, nullable=True)
    resumable: Mapped[int] = mapped_column(Integer, default=0)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    raw_log_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_json: Mapped[str | None] = mapped_column(RedactedText(json_content=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    job: Mapped[Job] = relationship(back_populates="steps")


class AgentHealth(Base):
    __tablename__ = "agent_health"
    agent: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, default="UNKNOWN")
    checked_at: Mapped[str] = mapped_column(String, default=utc_now)
    detail: Mapped[str | None] = mapped_column(RedactedText(), nullable=True)
    rate_limited_until: Mapped[str | None] = mapped_column(String, nullable=True)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    step_id: Mapped[str | None] = mapped_column(
        ForeignKey("job_steps.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String)
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    redacted: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String, default=utc_now)


class PairingCode(Base):
    __tablename__ = "pairing_codes"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    secret_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[str] = mapped_column(String)
    consumed_at: Mapped[str | None] = mapped_column(String, nullable=True)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    secret_hash: Mapped[str] = mapped_column(String(64), unique=True)
    tailscale_login: Mapped[str] = mapped_column(String)
    created_at: Mapped[str] = mapped_column(String)
    expires_at: Mapped[str] = mapped_column(String)
    revoked_at: Mapped[str | None] = mapped_column(String, nullable=True)


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    audit_step_id: Mapped[str] = mapped_column(ForeignKey("job_steps.id", ondelete="CASCADE"), index=True)
    audit_no: Mapped[int] = mapped_column(Integer)
    external_id: Mapped[str] = mapped_column(String)
    severity: Mapped[str] = mapped_column(String)
    file: Mapped[str] = mapped_column(RedactedText())
    line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(RedactedText())
    evidence: Mapped[str] = mapped_column(RedactedText())
    recommendation: Mapped[str] = mapped_column(RedactedText())
    triage_decision: Mapped[str | None] = mapped_column(String, nullable=True)
    triage_reason: Mapped[str | None] = mapped_column(RedactedText(), nullable=True)
    fixed_in_iteration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    __table_args__ = (Index("uq_findings_audit_external", "audit_step_id", "external_id", unique=True),)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    operation_json: Mapped[str] = mapped_column(Text)
    operation_hash: Mapped[str] = mapped_column(String(64), index=True)
    diff_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    decision: Mapped[str | None] = mapped_column(String, nullable=True)
    decision_idempotency_key: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    scope: Mapped[str | None] = mapped_column(String, nullable=True)
    reason: Mapped[str | None] = mapped_column(RedactedText(), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[str] = mapped_column(String, default=utc_now)
    decided_at: Mapped[str | None] = mapped_column(String, nullable=True)


class ApprovalGrant(Base):
    __tablename__ = "approval_grants"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    approval_id: Mapped[str] = mapped_column(ForeignKey("approvals.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    matcher_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String, default=utc_now)
