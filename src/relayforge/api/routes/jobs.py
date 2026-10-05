from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any, cast

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from relayforge.adapters.base import NormalizedEvent
from relayforge.api.schemas import JobCreate, JobDispatch, JobResume
from relayforge.api.sse import encode_stream
from relayforge.core.jobs import JobService
from relayforge.core.scheduler import JobScheduler
from relayforge.core.states import InvalidTransition

router = APIRouter(prefix="/api/jobs")


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message, "details": {}}}
    )


def _service(request: Request) -> JobService:
    return cast(JobService, request.app.state.jobs)


@router.post("")
async def create_job(
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JSONResponse:
    if not idempotency_key or not 1 <= len(idempotency_key) <= 128:
        return _error(400, "missing_idempotency_key", "Se requiere Idempotency-Key (1–128 caracteres).")
    try:
        payload = JobCreate.model_validate(await request.json())
    except (ValueError, ValidationError):
        return _error(422, "invalid_body", "La solicitud no cumple el contrato de creación del Job.")
    service = _service(request)
    try:
        job, created = service.create_job(
            payload.title,
            payload.request_text,
            idempotency_key,
            repository_id=payload.repository_id,
            workflow=payload.workflow,
            planning_agent=payload.agent,
            planning_model=payload.model,
            implementation_model=payload.implementation_model,
            audit_model=payload.audit_model,
            require_plan_approval=payload.require_plan_approval,
        )
    except ValueError:
        return _error(422, "invalid_repository", "El repositorio no existe o está deshabilitado.")
    if job["status"] == "QUEUED":
        cast(JobScheduler, request.app.state.job_scheduler).enqueue(str(job["id"]))
    return JSONResponse(status_code=202 if created else 200, content={"job": job})


@router.get("")
async def list_jobs(request: Request, repository_id: str | None = None) -> list[dict[str, Any]]:
    return _service(request).list_jobs(repository_id)


@router.post("/{job_id}/step", response_model=None)
async def dispatch_job_step(job_id: str, request: Request) -> dict[str, object] | JSONResponse:
    try:
        payload = JobDispatch.model_validate(await request.json())
    except (ValueError, ValidationError):
        return _error(422, "invalid_body", "La selección de agente/modelo no es válida.")
    try:
        return cast(JobScheduler, request.app.state.job_scheduler).dispatch_step(
            job_id, payload.agent, payload.model, payload.version
        )
    except LookupError:
        return _error(404, "job_not_found", "No existe el Job.")
    except (ValueError, RuntimeError) as exc:
        return _error(
            409, str(exc), "El Job está activo, cambió de versión o el agente no puede ejecutar esta etapa."
        )


@router.get("/{job_id}", response_model=None)
async def get_job(job_id: str, request: Request) -> dict[str, Any] | JSONResponse:
    job = _service(request).get_job(job_id)
    return job if job is not None else _error(404, "job_not_found", "No existe el Job.")


@router.post("/{job_id}/cancel", response_model=None)
async def cancel_job(job_id: str, request: Request) -> dict[str, object] | JSONResponse:
    scheduler = cast(JobScheduler, request.app.state.job_scheduler)
    try:
        return await scheduler.cancel(job_id)
    except LookupError:
        return _error(404, "job_not_found", "No existe el Job.")
    except InvalidTransition:
        return _error(
            409, "job_not_cancellable", "El Job ya terminó o no se puede cancelar en su estado actual."
        )


@router.post("/{job_id}/resume", response_model=None)
async def resume_job(job_id: str, request: Request) -> dict[str, object] | JSONResponse:
    try:
        payload = JobResume.model_validate(await request.json())
    except (ValueError, ValidationError):
        return _error(422, "invalid_body", "El modo de reanudación no es válido.")
    scheduler = cast(JobScheduler, request.app.state.job_scheduler)
    try:
        return scheduler.resume_interrupted(job_id, payload.mode)
    except LookupError:
        return _error(404, "job_not_found", "No existe el Job.")
    except ValueError as exc:
        code = str(exc)
        if code == "resume_token_missing":
            return _error(409, code, "No hay sesión guardada para reanudar; usa retry_step.")
        return _error(409, code, "Solo se pueden reanudar Jobs interrumpidos.")


@router.get("/{job_id}/events", response_model=None)
async def job_events(job_id: str, request: Request) -> StreamingResponse | JSONResponse:
    raw_cursor = request.headers.get("last-event-id", "0")
    try:
        cursor = int(raw_cursor or "0")
        if cursor < 0:
            raise ValueError
    except ValueError:
        return _error(400, "invalid_event_cursor", "Last-Event-ID debe ser un entero no negativo.")

    service = _service(request)
    conversation_id = service.get_job_conversation(job_id)
    if conversation_id is None:
        return _error(404, "job_not_found", "No existe el Job.")
    subscription = service.event_bus.subscribe(conversation_id)

    async def replay_then_follow() -> AsyncGenerator[NormalizedEvent]:
        last_seq = cursor
        try:
            _, replay = service.get_events(job_id, last_seq)
            for event in replay:
                seq = int(event.data.get("_seq", 0))
                if seq > last_seq:
                    last_seq = seq
                    yield event
            async for event in subscription:
                seq = int(event.data.get("_seq", 0))
                if seq <= last_seq:
                    continue
                last_seq = seq
                yield event
        finally:
            await subscription.aclose()

    return StreamingResponse(
        encode_stream(replay_then_follow(), conversation_id, job_id=job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
