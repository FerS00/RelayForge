from __future__ import annotations

from relayforge.core.jobs import JobService


def reconcile_jobs(service: JobService) -> None:
    """Mark non-resumable active Jobs interrupted before queued work resumes."""
    service.reconcile_active_jobs()
