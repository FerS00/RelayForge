from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    __tablename__ = "conversations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String, default="Nueva conversación")
    workspace_dir: Mapped[str] = mapped_column(Text)
    orchestrator: Mapped[str] = mapped_column(String, default="claude")
    session_id: Mapped[str] = mapped_column(String)
    session_established: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[str] = mapped_column(String, default=utc_now)
    updated_at: Mapped[str] = mapped_column(String, default=utc_now)
    messages: Mapped[list[Message]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
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
    step_id: Mapped[str | None] = mapped_column(String, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text)
