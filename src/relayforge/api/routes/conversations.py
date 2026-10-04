from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from relayforge.api.schemas import MessageCreate
from relayforge.core.chat import ChatService

router = APIRouter(prefix="/api/conversations")


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message, "details": {}}}
    )


def _service(request: Request) -> ChatService:
    return cast(ChatService, request.app.state.chat)


@router.get("")
def list_conversations(request: Request) -> list[dict[str, str]]:
    return _service(request).list_conversations()


@router.post("")
def create_conversation(request: Request, response: Response) -> dict[str, str]:
    response.status_code = 201
    return _service(request).create_conversation()


@router.get("/{conversation_id}", response_model=None)
def get_conversation(conversation_id: str, request: Request) -> dict[str, str] | JSONResponse:
    conversation = _service(request).get_conversation(conversation_id)
    return (
        conversation if conversation else _error(404, "conversation_not_found", "No existe la conversación.")
    )


@router.get("/{conversation_id}/messages", response_model=None)
def list_messages(conversation_id: str, request: Request) -> dict[str, Any] | JSONResponse:
    messages = _service(request).list_messages(conversation_id)
    return messages if messages else _error(404, "conversation_not_found", "No existe la conversación.")


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    if not idempotency_key or not 1 <= len(idempotency_key) <= 128:
        return _error(400, "missing_idempotency_key", "Se requiere Idempotency-Key (1–128 caracteres).")
    try:
        payload = MessageCreate.model_validate(await request.json())
    except (ValueError, ValidationError):
        return _error(422, "invalid_body", "El cuerpo debe contener un mensaje de 1 a 100000 caracteres.")
    message, status = _service(request).send_message(conversation_id, payload.content, idempotency_key)
    if status == "not_found":
        return _error(404, "conversation_not_found", "No existe la conversación.")
    if status == "active":
        return _error(409, "turn_in_progress", "La conversación ya tiene un turno activo.")
    return JSONResponse(status_code=200 if status == "replay" else 202, content={"message": message})
