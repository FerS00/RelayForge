from concurrent.futures import ThreadPoolExecutor

from relayforge.core.event_sequence import next_seq
from relayforge.db.models import Event, utc_now


def test_event_allocator_is_atomic_and_contiguous(app):
    conversation = app.state.chat.create_conversation()
    cid = conversation["id"]
    sessions = app.state.chat.sessions

    def allocate(index):
        with sessions.begin() as session:
            sequence = next_seq(session, cid)
            session.add(
                Event(
                    conversation_id=cid,
                    seq=sequence,
                    ts=utc_now(),
                    type="test",
                    actor="core",
                    payload_json="{}",
                )
            )
            return sequence

    with ThreadPoolExecutor(max_workers=4) as executor:
        sequences = list(executor.map(allocate, range(20)))
    assert sorted(sequences) == list(range(1, 21))
