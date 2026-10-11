from typing import Annotated, Any, Literal, cast

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from relayforge.core.actions import ActionError
from relayforge.core.chat import ChatService

router = APIRouter(prefix="/api/conversations")


class ActionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=0)
    operation_hash: str = Field(pattern="^[a-f0-9]{64}$")
    decision: Literal["approve", "reject"]


@router.post("/{conversation_id}/actions/{action_id}/decision")
async def decide(
    conversation_id: str,
    action_id: str,
    body: ActionDecision,
    request: Request,
    key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> dict[str, Any]:
    try:
        return await cast(ChatService, request.app.state.chat).decide_action(
            conversation_id, action_id, body.version, body.operation_hash, body.decision, key
        )
    except ActionError as exc:
        raise HTTPException(
            status_code=404 if str(exc) == "action_not_found" else 409, detail=str(exc)
        ) from exc
