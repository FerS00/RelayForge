from __future__ import annotations

import asyncio
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from relayforge.adapters.base import ConversationContext, NormalizedEvent
from relayforge.adapters.claude.orchestrator import ClaudeOrchestrator
from relayforge.core.events import EventBus
from relayforge.core.ids import new_ulid
from relayforge.db.models import Conversation, Event, Message, utc_now
from relayforge.security.redact import StreamingRedactor, redact_text, redact_value

logger = logging.getLogger("relayforge")


class ChatService:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        event_bus: EventBus,
        orchestrator: ClaudeOrchestrator,
        workspace_dir: Path,
    ) -> None:
        self.sessions = sessions
        self.event_bus = event_bus
        self.orchestrator = orchestrator
        self.workspace_dir = workspace_dir
        self.active: dict[str, str] = {}
        self.tasks: set[asyncio.Task[None]] = set()

    def create_conversation(self) -> dict[str, str]:
        now, identifier = utc_now(), new_ulid()
        row = Conversation(
            id=identifier,
            title="Nueva conversación",
            workspace_dir=str(self.workspace_dir),
            orchestrator="claude",
            session_id=str(uuid.uuid4()),
            session_established=0,
            created_at=now,
            updated_at=now,
        )
        with self.sessions.begin() as session:
            session.add(row)
        return self._conversation_dict(row)

    def list_conversations(self) -> list[dict[str, str]]:
        with self.sessions() as session:
            rows = session.scalars(select(Conversation).order_by(Conversation.updated_at.desc())).all()
            return [{"id": row.id, "title": row.title, "updated_at": row.updated_at} for row in rows]

    def get_conversation(self, conversation_id: str) -> dict[str, str] | None:
        with self.sessions() as session:
            row = session.get(Conversation, conversation_id)
            return self._conversation_dict(row) if row else None

    def list_messages(self, conversation_id: str) -> dict[str, Any] | None:
        with self.sessions() as session:
            if session.get(Conversation, conversation_id) is None:
                return None
            rows = session.scalars(
                select(Message).where(Message.conversation_id == conversation_id).order_by(Message.id)
            ).all()
            return {
                "messages": [self._message_dict(row) for row in rows],
                "active_step": {"step_id": self.active[conversation_id]}
                if conversation_id in self.active
                else None,
            }

    def send_message(
        self, conversation_id: str, content: str, idempotency_key: str
    ) -> tuple[dict[str, str] | None, str]:
        content = redact_text(content)
        with self.sessions.begin() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation is None:
                return None, "not_found"
            original = session.scalar(
                select(Message).where(
                    Message.conversation_id == conversation_id,
                    Message.idempotency_key == idempotency_key,
                )
            )
            if original is not None:
                return self._message_dict(original), "replay"
            if conversation_id in self.active:
                return None, "active"
            step_id, message_id, now = new_ulid(), new_ulid(), utc_now()
            message = Message(
                id=message_id,
                conversation_id=conversation_id,
                role="user",
                content=content,
                step_id=step_id,
                status="complete",
                idempotency_key=idempotency_key,
                ts=now,
            )
            data = {"kind": "chat", "agent": "claude", "message_id": message_id}
            event = self._new_event(session, conversation_id, "step.started", "core", step_id, data, now)
            session.add_all([message, event])
            conversation.updated_at = now
            if conversation.title == "Nueva conversación":
                conversation.title = " ".join(content.split())[:60] or "Nueva conversación"
            response = self._message_dict(message)
        self.active[conversation_id] = step_id
        self.event_bus.publish(
            conversation_id,
            NormalizedEvent("step.started", "core", step_id, {**data, "_seq": event.seq}, now),
        )
        context = self._context(conversation_id, step_id)
        task = asyncio.create_task(self._run_turn(context, step_id, content))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return response, "created"

    async def _run_turn(self, context: ConversationContext, step_id: str, prompt: str) -> None:
        fragment_ids: dict[int, str] = {}
        stream_redactors: dict[int, StreamingRedactor] = {}
        outcome, detail, duration_ms = "invalid_output", None, 0
        try:
            async for event in self.orchestrator.chat(context, prompt):
                if event.type == "agent.message.delta":
                    index = int(event.data.pop("_message_index", 0))
                    message_id = fragment_ids.setdefault(index, new_ulid())
                    redactor = stream_redactors.setdefault(index, StreamingRedactor())
                    safe_fragment = redactor.push(event.data["text"])
                    if safe_fragment:
                        data = {"message_id": message_id, "text": safe_fragment}
                        await self._persist_publish(context.conversation_id, event, data, None)
                elif event.type == "agent.message":
                    index = int(event.data.pop("_message_index", 0))
                    message_id = fragment_ids.get(index, new_ulid())
                    message_redactor = stream_redactors.get(index)
                    if message_redactor is not None:
                        del stream_redactors[index]
                        tail = message_redactor.finish()
                        if tail:
                            await self._persist_publish(
                                context.conversation_id,
                                NormalizedEvent("agent.message.delta", "claude", step_id, {}),
                                {"message_id": message_id, "text": tail},
                                None,
                            )
                    safe_text = redact_text(event.data["text"])
                    data = {"message_id": message_id, "text": safe_text}
                    row = Message(
                        id=message_id,
                        conversation_id=context.conversation_id,
                        role="orchestrator",
                        content=safe_text,
                        step_id=step_id,
                        status="complete",
                        ts=utc_now(),
                    )
                    self._establish_session(context.conversation_id)
                    await self._persist_publish(context.conversation_id, event, data, row)
                elif event.type == "agent.result":
                    continue
                elif event.type == "agent.exit":
                    outcome = event.data["outcome"]
                    detail = event.data.get("detail")
                    duration_ms = event.data.get("duration_ms", 0)
        except (OSError, ValueError, RuntimeError) as exc:
            outcome, detail = "start_failed", type(exc).__name__
            logger.warning(
                "agent start failed conversation=%s step=%s error=%s",
                context.conversation_id,
                step_id,
                type(exc).__name__,
            )
        except asyncio.CancelledError:
            outcome, detail = "server_shutdown", "server_shutdown"
            raise
        finally:
            error_id: str | None
            error_message: Message | None
            if outcome != "ok":
                error_id = new_ulid()
                error_text = "Claude no pudo completar el turno."
                error_message = Message(
                    id=error_id,
                    conversation_id=context.conversation_id,
                    role="orchestrator",
                    content=error_text,
                    step_id=step_id,
                    status="error",
                    ts=utc_now(),
                )
            else:
                error_id, error_message = None, None
            finish_data: dict[str, Any] = {
                "kind": "chat",
                "agent": "claude",
                "outcome": outcome,
                "duration_ms": duration_ms,
            }
            if error_id:
                finish_data["message_id"] = error_id
            if detail:
                finish_data["detail"] = str(detail)[:300]
            await self._persist_publish(
                context.conversation_id,
                NormalizedEvent("step.finished", "core", step_id, finish_data),
                finish_data,
                error_message,
            )
            self.active.pop(context.conversation_id, None)

    def _establish_session(self, conversation_id: str) -> None:
        with self.sessions.begin() as session:
            conversation = session.get(Conversation, conversation_id)
            if conversation:
                conversation.session_established = 1

    async def _persist_publish(
        self, conversation_id: str, event: NormalizedEvent, data: dict[str, Any], message: Message | None
    ) -> None:
        data = redact_value(data)
        now = utc_now()
        with self.sessions.begin() as session:
            stored = self._new_event(
                session, conversation_id, event.type, event.actor, event.step_id, {"data": data}, now
            )
            seq = stored.seq
            session.add(stored)
            if message is not None:
                session.add(message)
            conversation = session.get(Conversation, conversation_id)
            if conversation:
                conversation.updated_at = now
        self.event_bus.publish(
            conversation_id,
            NormalizedEvent(event.type, event.actor, event.step_id, {**data, "_seq": seq}, now),
        )
        logger.debug(
            "event persisted conversation=%s type=%s bytes=%d",
            conversation_id,
            event.type,
            len(json.dumps(data, ensure_ascii=False)),
        )

    @staticmethod
    def _new_event(
        session: Session,
        conversation_id: str,
        kind: str,
        actor: str,
        step_id: str | None,
        data: dict[str, Any],
        now: str,
    ) -> Event:
        current = (
            session.scalar(select(func.max(Event.seq)).where(Event.conversation_id == conversation_id)) or 0
        )
        return Event(
            conversation_id=conversation_id,
            seq=current + 1,
            ts=now,
            type=kind,
            actor=actor,
            step_id=step_id,
            payload_json=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        )

    def _context(self, conversation_id: str, step_id: str) -> ConversationContext:
        with self.sessions() as session:
            row = session.get(Conversation, conversation_id)
            assert row is not None
            if not row.session_established:
                row.session_id = str(uuid.uuid4())
                session.commit()
            return ConversationContext(
                conversation_id=row.id,
                session_id=row.session_id,
                session_established=bool(row.session_established),
                cwd=Path(row.workspace_dir),
                step_id=step_id,
            )

    @staticmethod
    def _conversation_dict(row: Conversation) -> dict[str, str]:
        return {"id": row.id, "title": row.title, "created_at": row.created_at, "updated_at": row.updated_at}

    @staticmethod
    def _message_dict(row: Message) -> dict[str, str]:
        return {
            "id": row.id,
            "step_id": row.step_id,
            "role": row.role,
            "content": row.content,
            "status": row.status,
            "ts": row.ts,
        }
