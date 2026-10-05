import asyncio
import json

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from relayforge.adapters.base import NormalizedEvent
from relayforge.core.events import EventBus
from relayforge.db.models import Base, Conversation, Event, Message


def test_sensitive_content_is_redacted_before_database_storage() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    token = "ghp_" + "123456789012345678901234"
    with sessions.begin() as session:
        session.add(
            Conversation(
                id="conversation",
                title="password=synthetic-title",
                workspace_dir="/tmp/workspace",
                session_id="session",
            )
        )
        session.add(
            Message(
                id="message",
                conversation_id="conversation",
                role="orchestrator",
                content="Authorization: Bearer synthetic-bearer-token",
                step_id="step",
            )
        )
        session.add(
            Event(
                conversation_id="conversation",
                seq=1,
                ts="2026-10-04T00:00:00Z",
                type="agent.message",
                actor="claude",
                payload_json=json.dumps({"data": {"text": token}}),
            )
        )

    with engine.connect() as connection:
        raw = " ".join(
            connection.execute(text(f"SELECT {column} FROM {table}")).scalar_one()
            for table, column in (
                ("conversations", "title"),
                ("messages", "content"),
                ("events", "payload_json"),
            )
        )
    assert "synthetic-title" not in raw
    assert "synthetic-bearer-token" not in raw
    assert token not in raw
    engine.dispose()


def test_event_bus_redacts_before_sse_delivery() -> None:
    async def scenario() -> dict[str, object]:
        bus = EventBus()
        stream = bus.subscribe("conversation")
        pending = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)
        bus.publish(
            "conversation",
            NormalizedEvent("agent.message", "claude", None, {"text": "password=synthetic-value"}),
        )
        result = await pending
        await stream.aclose()
        return result.data

    assert asyncio.run(scenario()) == {"text": "password=[REDACTED]"}


def test_redacted_database_values_remain_valid_json() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine)
    with sessions.begin() as session:
        session.add(Conversation(id="conversation", title="safe", workspace_dir="/tmp", session_id="session"))
        session.add(
            Event(
                conversation_id="conversation",
                seq=1,
                ts="2026-10-04T00:00:00Z",
                type="job.plan",
                actor="claude",
                payload_json='{"data":{"api_key":"synthetic"}}',
            )
        )
    with sessions() as session:
        event = session.scalar(select(Event))
        assert event is not None
        assert event.payload_json == '{"data":{"api_key":"[REDACTED]"}}'
    engine.dispose()
