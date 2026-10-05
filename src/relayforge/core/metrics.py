from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from relayforge.db.models import Finding, Job, JobStep


def _duration(started: str | None, finished: str | None) -> float | None:
    if not started or not finished:
        return None
    try:
        start = datetime.fromisoformat(started.replace("Z", "+00:00"))
        end = datetime.fromisoformat(finished.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (end - start).total_seconds())


class MetricsService:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def summary(self, start: str | None = None, end: str | None = None) -> dict[str, Any]:
        predicates = []
        if start is not None:
            predicates.append(Job.created_at >= start)
        if end is not None:
            predicates.append(Job.created_at < end)
        with self.sessions() as session:
            jobs = session.scalars(select(Job).where(*predicates).order_by(Job.created_at)).all()
            job_ids = [job.id for job in jobs]
            steps = (
                session.scalars(select(JobStep).where(JobStep.job_id.in_(job_ids))).all() if job_ids else []
            )
            findings = (
                session.scalars(select(Finding).where(Finding.job_id.in_(job_ids))).all() if job_ids else []
            )
            jobs_by_status = self._count(job.status for job in jobs)
            jobs_by_workflow = self._count(job.workflow for job in jobs)
            job_durations = [
                duration
                for job in jobs
                if (duration := _duration(job.created_at, job.finished_at)) is not None
            ]
            agent_totals: dict[str, dict[str, float | int]] = {}
            checks = {"passed": 0, "failed": 0, "skipped": 0}
            failed_steps = 0
            for step in steps:
                aggregate = agent_totals.setdefault(
                    step.agent, {"steps": 0, "failed": 0, "duration_seconds": 0.0}
                )
                aggregate["steps"] = int(aggregate["steps"]) + 1
                if step.status in {"FAILED", "TIMED_OUT"}:
                    aggregate["failed"] = int(aggregate["failed"]) + 1
                    failed_steps += 1
                duration = _duration(step.started_at, step.finished_at)
                if duration is not None:
                    aggregate["duration_seconds"] = float(aggregate["duration_seconds"]) + duration
                if step.kind == "checks" and step.summary_json:
                    payload = json.loads(step.summary_json)
                    for result in payload.get("results", []):
                        status = result.get("status")
                        if status in checks:
                            checks[status] += 1
            return {
                "from": start,
                "to": end,
                "total_jobs": len(jobs),
                "jobs_by_status": jobs_by_status,
                "jobs_by_workflow": jobs_by_workflow,
                "average_job_duration_seconds": round(sum(job_durations) / len(job_durations), 3)
                if job_durations
                else None,
                "retry_count": sum(job.retry_count for job in jobs),
                "step_count": len(steps),
                "failed_steps": failed_steps,
                "steps_by_agent": agent_totals,
                "checks": checks,
                "findings_by_severity": self._count(finding.severity for finding in findings),
            }

    @staticmethod
    def _count(values: Any) -> dict[str, int]:
        counts: dict[str, int] = {}
        for value in values:
            counts[str(value)] = counts.get(str(value), 0) + 1
        return counts


def parse_metric_date(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Fecha ISO-8601 inválida.") from exc
    if parsed.tzinfo is None:
        raise ValueError("La fecha debe incluir zona horaria.")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
