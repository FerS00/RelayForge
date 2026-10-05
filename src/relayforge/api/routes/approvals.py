from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Header, HTTPException, Request

from relayforge.api.schemas import ApprovalDecision
from relayforge.core.approvals import ApprovalConflict

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


@router.get("")
def list_approvals(request: Request, status: str = "pending") -> list[dict[str, object]]:
    if status != "pending":
        raise HTTPException(status_code=400, detail="Solo se admite status=pending.")
    return cast(list[dict[str, object]], request.app.state.approvals.list_pending())


@router.post("/{approval_id}/decision")
async def decide_approval(
    approval_id: str,
    body: ApprovalDecision,
    request: Request,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
) -> dict[str, object]:
    try:
        result = request.app.state.approvals.decide(
            approval_id,
            decision=body.decision,
            scope=body.scope,
            reason=body.reason,
            idempotency_key=idempotency_key,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Aprobación no encontrada.") from exc
    except ApprovalConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.decision == "approve":
        job = request.app.state.jobs.get_job(str(result["job_id"]))
        if job is not None and job.get("approval_kind") == "plan":
            request.app.state.job_scheduler.resume_plan(str(result["job_id"]))
        else:
            request.app.state.job_scheduler.resume_delivery(str(result["job_id"]))
    request.app.state.jobs.record_job_event(
        str(result["job_id"]),
        "approval.decided",
        "user",
        None,
        {"approval_id": approval_id, "decision": body.decision, "scope": body.scope},
    )
    return cast(dict[str, object], result)
