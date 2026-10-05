from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from relayforge.db.models import AuthSession, PairingCode

SESSION_TTL = timedelta(days=14)
PAIR_TTL = timedelta(minutes=10)


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class AuthService:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def issue_pairing_code(self) -> str:
        code = secrets.token_urlsafe(24)
        now = _now()
        with self.sessions.begin() as session:
            session.query(PairingCode).delete()
            session.add(
                PairingCode(
                    id=secrets.token_hex(16), secret_hash=_digest(code), expires_at=_stamp(now + PAIR_TTL)
                )
            )
        return code

    def pair(self, code: str, tailscale_login: str) -> str | None:
        now = _now()
        with self.sessions.begin() as session:
            pairing = session.scalar(
                select(PairingCode).where(PairingCode.consumed_at.is_(None)).with_for_update()
            )
            if (
                pairing is None
                or pairing.expires_at <= _stamp(now)
                or not secrets.compare_digest(pairing.secret_hash, _digest(code))
            ):
                return None
            pairing.consumed_at = _stamp(now)
            token = secrets.token_urlsafe(32)
            session.add(
                AuthSession(
                    id=secrets.token_hex(16),
                    secret_hash=_digest(token),
                    tailscale_login=tailscale_login,
                    created_at=_stamp(now),
                    expires_at=_stamp(now + SESSION_TTL),
                )
            )
            return token

    def is_valid(self, token: str, tailscale_login: str) -> bool:
        now = _stamp(_now())
        with self.sessions() as session:
            row = session.scalar(
                select(AuthSession).where(
                    AuthSession.secret_hash == _digest(token),
                    AuthSession.tailscale_login == tailscale_login,
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > now,
                )
            )
            return row is not None

    def revoke(self, token: str) -> None:
        with self.sessions.begin() as session:
            row = session.scalar(select(AuthSession).where(AuthSession.secret_hash == _digest(token)))
            if row is not None and row.revoked_at is None:
                row.revoked_at = _stamp(_now())
