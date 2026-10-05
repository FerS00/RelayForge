from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from relayforge.adapters.base import NormalizedEvent


async def encode_stream(
    iterator: AsyncGenerator[NormalizedEvent], conversation_id: str, *, job_id: str | None = None
) -> AsyncGenerator[str]:
    pending: asyncio.Task[NormalizedEvent] = asyncio.create_task(iterator.__anext__())
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=15)
            if not done:
                yield ": ping\n\n"
                continue
            try:
                event: NormalizedEvent = pending.result()
            except StopAsyncIteration:
                return
            seq = int(event.data.get("_seq", 0))
            data = {key: value for key, value in event.data.items() if not key.startswith("_")}
            document = {
                "conversation": conversation_id,
                "seq": seq,
                "ts": event.ts,
                "type": event.type,
                "actor": event.actor,
                "step": event.step_id,
                "data": data,
            }
            if job_id is not None:
                document["job"] = job_id
            encoded = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
            event_name = "job.event" if job_id is not None else "conversation.event"
            yield f"id: {seq}\nevent: {event_name}\ndata: {encoded}\n\n"
            pending = asyncio.create_task(iterator.__anext__())
    finally:
        pending.cancel()
        await iterator.aclose()
