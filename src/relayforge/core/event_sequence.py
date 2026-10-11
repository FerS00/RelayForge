from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from relayforge.db.models import Conversation, Event


def next_seq(session: Session, conversation_id: str) -> int:
    # The UPDATE is a database write lock, not a read/compute race. The max
    # also keeps legacy/imported events compatible with the allocator.
    maximum = (
        select(func.coalesce(func.max(Event.seq), 0) + 1)
        .where(Event.conversation_id == conversation_id)
        .scalar_subquery()
    )
    value = session.scalar(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(next_event_seq=func.max(Conversation.next_event_seq, maximum) + 1)
        .returning(Conversation.next_event_seq)
    )
    if value is None:
        raise ValueError("conversation_not_found")
    return int(value) - 1
