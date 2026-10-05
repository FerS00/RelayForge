from __future__ import annotations

from enum import StrEnum


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    PLANNING = "PLANNING"
    IMPLEMENTING = "IMPLEMENTING"
    TESTING = "TESTING"
    AUDITING = "AUDITING"
    TRIAGING = "TRIAGING"
    REVISING = "REVISING"
    FINAL_REVIEW = "FINAL_REVIEW"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    WAITING_RETRY = "WAITING_RETRY"
    WAITING_AGENT = "WAITING_AGENT"
    DELIVERING = "DELIVERING"
    INTERRUPTED = "INTERRUPTED"
    CANCELLING = "CANCELLING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


TERMINAL_STATES = frozenset({JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED})
ACTIVE_STATES = frozenset(
    {
        JobStatus.PREPARING,
        JobStatus.PLANNING,
        JobStatus.IMPLEMENTING,
        JobStatus.TESTING,
        JobStatus.AUDITING,
        JobStatus.TRIAGING,
        JobStatus.REVISING,
        JobStatus.FINAL_REVIEW,
        JobStatus.DELIVERING,
        JobStatus.CANCELLING,
    }
)

TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset({JobStatus.PREPARING, JobStatus.CANCELLING}),
    JobStatus.PREPARING: frozenset(
        {
            JobStatus.PLANNING,
            JobStatus.FAILED,
            JobStatus.WAITING_RETRY,
            JobStatus.INTERRUPTED,
            JobStatus.CANCELLING,
        }
    ),
    JobStatus.PLANNING: frozenset(
        {
            JobStatus.WAITING_APPROVAL,
            JobStatus.IMPLEMENTING,
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.WAITING_RETRY,
            JobStatus.INTERRUPTED,
            JobStatus.CANCELLING,
        }
    ),
    JobStatus.IMPLEMENTING: frozenset(
        {
            JobStatus.TESTING,
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.WAITING_RETRY,
            JobStatus.INTERRUPTED,
            JobStatus.CANCELLING,
        }
    ),
    JobStatus.TESTING: frozenset(
        {
            JobStatus.AUDITING,
            JobStatus.FINAL_REVIEW,
            JobStatus.COMPLETED,
            JobStatus.TRIAGING,
            JobStatus.FAILED,
            JobStatus.WAITING_RETRY,
            JobStatus.INTERRUPTED,
            JobStatus.CANCELLING,
        }
    ),
    JobStatus.AUDITING: frozenset(
        {
            JobStatus.TRIAGING,
            JobStatus.FINAL_REVIEW,
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.WAITING_RETRY,
            JobStatus.INTERRUPTED,
            JobStatus.CANCELLING,
        }
    ),
    JobStatus.TRIAGING: frozenset(
        {
            JobStatus.REVISING,
            JobStatus.FINAL_REVIEW,
            JobStatus.COMPLETED,
            JobStatus.WAITING_APPROVAL,
            JobStatus.FAILED,
            JobStatus.WAITING_RETRY,
            JobStatus.INTERRUPTED,
            JobStatus.CANCELLING,
        }
    ),
    JobStatus.REVISING: frozenset(
        {
            JobStatus.TESTING,
            JobStatus.FAILED,
            JobStatus.WAITING_RETRY,
            JobStatus.INTERRUPTED,
            JobStatus.CANCELLING,
        }
    ),
    JobStatus.FINAL_REVIEW: frozenset(
        {
            JobStatus.WAITING_APPROVAL,
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.INTERRUPTED,
            JobStatus.CANCELLING,
        }
    ),
    JobStatus.WAITING_APPROVAL: frozenset(
        {JobStatus.IMPLEMENTING, JobStatus.DELIVERING, JobStatus.FAILED, JobStatus.CANCELLING}
    ),
    JobStatus.WAITING_RETRY: frozenset(
        {
            JobStatus.QUEUED,
            JobStatus.PREPARING,
            JobStatus.PLANNING,
            JobStatus.IMPLEMENTING,
            JobStatus.TESTING,
            JobStatus.AUDITING,
            JobStatus.FAILED,
            JobStatus.CANCELLING,
        }
    ),
    JobStatus.WAITING_AGENT: frozenset(
        {
            JobStatus.QUEUED,
            JobStatus.IMPLEMENTING,
            JobStatus.AUDITING,
            JobStatus.TRIAGING,
            JobStatus.CANCELLING,
        }
    ),
    JobStatus.DELIVERING: frozenset(
        {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.INTERRUPTED, JobStatus.CANCELLING}
    ),
    JobStatus.INTERRUPTED: frozenset(
        {
            JobStatus.QUEUED,
            JobStatus.PREPARING,
            JobStatus.PLANNING,
            JobStatus.IMPLEMENTING,
            JobStatus.TESTING,
            JobStatus.AUDITING,
            JobStatus.FAILED,
            JobStatus.CANCELLING,
        }
    ),
    JobStatus.CANCELLING: frozenset({JobStatus.CANCELLED}),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.FAILED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}

# Authentication and quota failures await an explicit provider decision.
for _state in ACTIVE_STATES - {JobStatus.CANCELLING, JobStatus.DELIVERING}:
    TRANSITIONS[_state] = TRANSITIONS[_state] | {JobStatus.WAITING_AGENT}
for _state in (JobStatus.WAITING_RETRY, JobStatus.INTERRUPTED):
    TRANSITIONS[_state] = TRANSITIONS[_state] | {JobStatus.TRIAGING}


class InvalidTransition(ValueError):
    pass


def validate_transition(current: str | JobStatus, target: str | JobStatus) -> tuple[JobStatus, JobStatus]:
    try:
        source_state, target_state = JobStatus(current), JobStatus(target)
    except ValueError as exc:
        raise InvalidTransition("Estado de Job desconocido.") from exc
    if target_state not in TRANSITIONS[source_state]:
        raise InvalidTransition(f"Transición no permitida: {source_state} -> {target_state}.")
    return source_state, target_state
