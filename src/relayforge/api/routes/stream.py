from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from relayforge.api.sse import encode_stream
from relayforge.core.chat import ChatService

router = APIRouter(prefix="/api/stream")


@router.get("", response_model=None)
async def stream(
    request: Request, conversation: str = Query(min_length=1)
) -> StreamingResponse | JSONResponse:
    service = cast(ChatService, request.app.state.chat)
    if service.get_conversation(conversation) is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "conversation_not_found",
                    "message": "No existe la conversación.",
                    "details": {},
                }
            },
        )
    subscription = service.event_bus.subscribe(conversation)
    return StreamingResponse(
        encode_stream(subscription, conversation),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
