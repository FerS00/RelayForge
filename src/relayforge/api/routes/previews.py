from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from relayforge.core.previews import PreviewError, PreviewService
from relayforge.db.models import Conversation

router = APIRouter()


def _error(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": code, "details": {}}},
    )


@router.get("/api/conversations/{conversation_id}/previews", response_model=None)
def list_previews(conversation_id: str, request: Request) -> dict[str, Any] | JSONResponse:
    with Session(request.app.state.engine) as session:
        if session.get(Conversation, conversation_id) is None:
            return _error(404, "conversation_not_found")
    service: PreviewService = request.app.state.previews
    return {
        "items": service.list_for_conversation(conversation_id),
        "available": service.gateway_available,
        "error_code": service.gateway_error,
    }


@router.post("/api/previews/{preview_id}/ticket", response_model=None)
def issue_ticket(preview_id: str, request: Request) -> dict[str, Any] | JSONResponse:
    try:
        url = request.app.state.preview_gateway.issue_ticket(preview_id)
    except ValueError as exc:
        code = str(exc)
        return _error(404 if code == "preview_not_found" else 409, code)
    return {"url": url, "expires_in": 120}


@router.post("/api/previews/{preview_id}/stop", response_model=None)
async def stop_preview(preview_id: str, request: Request) -> dict[str, Any] | JSONResponse:
    try:
        service: PreviewService = request.app.state.previews
        return await service.stop(preview_id, "user")
    except PreviewError as exc:
        return _error(404, exc.code)
