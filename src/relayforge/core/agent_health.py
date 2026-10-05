from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from relayforge.db.models import AgentHealth, Event, JobStep, utc_now


def classify_failure(message: str) -> str:
    """Classify only stable, recognizable transient/auth signals; default closed."""
    text = message.lower()
    if any(
        token in text
        for token in (
            "rate limit",
            "rate_limit",
            "too many requests",
            "429",
            "insufficient_quota",
            "usage limit",
            "quota exceeded",
            "quota exhausted",
            "hit your limit",
        )
    ):
        return "rate_limited"
    if any(
        token in text
        for token in ("network", "connection reset", "connection refused", "timed out", "name resolution")
    ):
        return "network"
    if any(
        token in text
        for token in (
            "unauthorized",
            "authentication required",
            "invalid api key",
            "login required",
            "auth_required",
            "oauth token expired",
            "session expired",
            "not logged in",
        )
    ):
        return "auth_required"
    if "invalid_output" in text or "invalid json" in text:
        return "invalid_output"
    return "unknown"


class AgentHealthService:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def usage(self, agent: str) -> dict[str, Any]:
        with self.sessions() as session:
            steps = session.scalars(
                select(JobStep).where(JobStep.agent == agent, JobStep.started_at.is_not(None))
            ).all()
            events = session.scalars(
                select(Event).where(Event.actor == agent, Event.type == "agent.usage")
            ).all()
            turns = session.scalars(
                select(Event).where(Event.actor == agent, Event.type == "agent.turn_started")
            ).all()
            totals = {"input_tokens": 0, "output_tokens": 0}
            known = {"input_tokens": False, "output_tokens": False}
            for event in events:
                data = json.loads(event.payload_json).get("data", {})
                for key in totals:
                    count = data.get(key)
                    if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
                        totals[key] += count
                        known[key] = True
            return {
                "turns": len(turns),
                "steps": len(steps),
                **{key: totals[key] if known[key] else None for key in totals},
                "five_hour": {"status": "unknown", "remaining": None},
                "weekly": {"status": "unknown", "remaining": None},
            }

    def record_failure(self, agent: str, classification: str, retry_at: str | None) -> None:
        status = (
            "RATE_LIMITED"
            if classification == "rate_limited"
            else "AUTH_REQUIRED"
            if classification == "auth_required"
            else "DEGRADED"
        )
        with self.sessions.begin() as session:
            row = session.get(AgentHealth, agent)
            if row is None:
                row = AgentHealth(agent=agent, status=status, checked_at=utc_now())
                session.add(row)
            row.status = status
            row.checked_at = utc_now()
            row.detail = classification
            row.rate_limited_until = retry_at if classification == "rate_limited" else None

    def record_recovered(self, agent: str) -> None:
        with self.sessions.begin() as session:
            row = session.get(AgentHealth, agent)
            if row is not None:
                row.status = "READY"
                row.checked_at = utc_now()
                row.detail = None
                row.rate_limited_until = None

    def list(self) -> list[dict[str, str | None]]:
        with self.sessions() as session:
            rows = session.scalars(select(AgentHealth).order_by(AgentHealth.agent)).all()
            return [
                {
                    "agent": row.agent,
                    "status": row.status,
                    "checked_at": row.checked_at,
                    "detail": row.detail,
                    "rate_limited_until": row.rate_limited_until,
                }
                for row in rows
            ]


def retry_time(retry_count: int, *, now: datetime | None = None) -> str:
    moment = now or datetime.now(UTC)
    delay = min(300, 30 * (2 ** min(retry_count, 4)))
    return (moment + timedelta(seconds=delay)).isoformat().replace("+00:00", "Z")
