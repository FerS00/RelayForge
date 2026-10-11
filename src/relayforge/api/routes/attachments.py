from __future__ import annotations

import json
from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse

from relayforge.api.schemas import AttachmentCreate
from relayforge.core.attachments import MAX_BODY, AttachmentError, AttachmentService

router = APIRouter(prefix="/api/conversations/{conversation_id}/attachments")


def error(exc: AttachmentError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={
            "error": {
                "code": exc.code,
                "message": f"No se pudo procesar el adjunto ({exc.code}).",
                "details": {},
            }
        },
    )


def service(request: Request) -> AttachmentService:
    return cast(AttachmentService, request.app.state.attachments)


@router.post("", response_model=None)
async def upload(conversation_id: str, request: Request) -> JSONResponse:
    try:
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BODY:
                raise AttachmentError("attachment_body_limit", 413)
            chunks.append(chunk)
        payload = AttachmentCreate.model_validate(json.loads(b"".join(chunks)))
        row = service(request).create(conversation_id, payload.name, payload.data_base64)
        return JSONResponse(status_code=201, content=row)
    except AttachmentError as exc:
        return error(exc)
    except (ValueError, UnicodeError):
        return error(AttachmentError("attachment_body_invalid"))


@router.get("/{attachment_id}", response_model=None)
def metadata(conversation_id: str, attachment_id: str, request: Request) -> dict[str, Any] | JSONResponse:
    try:
        return service(request).metadata(service(request).get(conversation_id, attachment_id))
    except AttachmentError as exc:
        return error(exc)


@router.get("/{attachment_id}/content", response_model=None)
def content(conversation_id: str, attachment_id: str, request: Request) -> FileResponse | JSONResponse:
    try:
        row = service(request).get(conversation_id, attachment_id)
        path = service(request).path(row)
        return FileResponse(
            path,
            media_type=row.media_type,
            filename=row.name,
            content_disposition_type="inline" if row.media_type.startswith("image/") else "attachment",
            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"},
        )
    except (OSError, AttachmentError):
        return error(AttachmentError("attachment_not_available", 404))
