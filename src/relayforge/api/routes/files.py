from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from relayforge.core.deliverables import (
    DeliverableError,
    Root,
    find_root,
    list_directory,
    read_file,
    roots,
    zip_stream,
)
from relayforge.db.models import Conversation

router = APIRouter()


def _error(code: str) -> JSONResponse:
    status = {
        "file_not_found": 404,
        "path_rejected": 400,
        "zip_too_large": 413,
        "file_too_large": 413,
    }.get(code, 404)
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": code, "details": {}}},
    )


def _find_root(request: Request, conversation_id: str, root_ref: str) -> Root:
    with Session(request.app.state.engine) as session:
        return find_root(session, conversation_id, root_ref or "workspace")


@router.get("/api/conversations/{conversation_id}/files/roots", response_model=None)
def list_roots(conversation_id: str, request: Request) -> dict[str, object] | JSONResponse:
    with Session(request.app.state.engine) as session:
        if session.get(Conversation, conversation_id) is None:
            return _error("file_not_found")
        available = roots(session, conversation_id)
        return {"roots": [{"id": item.ref, "name": item.name} for item in available]}


@router.get("/api/conversations/{conversation_id}/files", response_model=None)
def browse_files(
    conversation_id: str, request: Request, root: str = "workspace", path: str = ""
) -> dict[str, object] | JSONResponse:
    try:
        item = _find_root(request, conversation_id, root)
        return {"root": item.ref, "path": path, **list_directory(item, path)}
    except DeliverableError as exc:
        return _error(exc.code)


@router.get("/api/conversations/{conversation_id}/files/content")
def download_file(
    conversation_id: str, request: Request, root: str = "workspace", path: str = ""
) -> Response:
    try:
        item = _find_root(request, conversation_id, root)
        file_path, content = read_file(item, path)
    except DeliverableError as exc:
        return _error(exc.code)
    return Response(
        content=content,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(file_path.name, safe='')}",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )


@router.get("/api/conversations/{conversation_id}/files/zip")
def download_zip(conversation_id: str, request: Request, root: str = "workspace", path: str = "") -> Response:
    try:
        item = _find_root(request, conversation_id, root)
        archive = zip_stream(item, path, request.app.state.settings.home / "data" / "tmp")
    except DeliverableError as exc:
        return _error(exc.code)

    async def stream() -> AsyncIterator[bytes]:
        try:
            with archive.open("rb") as source:
                while chunk := await asyncio.to_thread(source.read, 1024 * 1024):
                    yield chunk
        finally:
            archive.unlink(missing_ok=True)

    return StreamingResponse(
        stream(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="deliverables.zip"'},
    )
