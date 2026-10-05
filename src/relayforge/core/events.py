from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncGenerator
from dataclasses import replace

from relayforge.adapters.base import NormalizedEvent
from relayforge.security.redact import redact_value


class EventBus:
    def __init__(self, queue_size: int = 1000) -> None:
        self._queues: dict[str, set[asyncio.Queue[NormalizedEvent | None]]] = defaultdict(set)
        self._queue_size = queue_size

    def publish(self, conversation_id: str, event: NormalizedEvent) -> None:
        event = replace(event, data=redact_value(event.data))
        for queue in tuple(self._queues[conversation_id]):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                self._queues[conversation_id].discard(queue)
                try:
                    queue.get_nowait()
                    queue.put_nowait(None)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    def subscribe(self, conversation_id: str) -> AsyncGenerator[NormalizedEvent]:
        queue: asyncio.Queue[NormalizedEvent | None] = asyncio.Queue(self._queue_size)
        self._queues[conversation_id].add(queue)

        async def events() -> AsyncGenerator[NormalizedEvent]:
            try:
                while (event := await queue.get()) is not None:
                    yield event
            finally:
                self._queues[conversation_id].discard(queue)
                if not self._queues[conversation_id]:
                    self._queues.pop(conversation_id, None)

        return events()
