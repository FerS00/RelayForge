from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from relayforge.adapters.checks import ChecksAdapter, ChecksValidationError
from relayforge.api.schemas import RepositoryCreate
from relayforge.core.repositories import RepositoryError, RepositoryService

router = APIRouter(prefix="/api/repos")


@router.get("")
def list_repositories(request: Request) -> list[dict[str, Any]]:
    return cast(RepositoryService, request.app.state.repositories).list()


@router.post("", status_code=201)
async def create_repository(request: Request) -> JSONResponse:
    try:
        payload = RepositoryCreate.model_validate(await request.json())
        service = cast(RepositoryService, request.app.state.repositories)
        check_commands = [command.json() for command in ChecksAdapter.parse_many(payload.check_commands)]
        if payload.mode == "create":
            if payload.path is not None:
                return JSONResponse(
                    status_code=422,
                    content={"error": {"code": "invalid_body", "message": "create no acepta path"}},
                )
            result = service.create(payload.name, check_commands)
        else:
            if payload.path is None:
                return JSONResponse(
                    status_code=422,
                    content={"error": {"code": "invalid_body", "message": "register requiere path"}},
                )
            result = service.register(payload.name, payload.path, payload.default_branch, check_commands)
        return JSONResponse(status_code=201, content={"repository": result})
    except ChecksValidationError as exc:
        return JSONResponse(
            status_code=422, content={"error": {"code": "invalid_check_command", "message": str(exc)}}
        )
    except RepositoryError as exc:
        return JSONResponse(
            status_code=409, content={"error": {"code": "repository_rejected", "message": str(exc)}}
        )
    except (ValueError, ValidationError):
        return JSONResponse(
            status_code=422, content={"error": {"code": "invalid_body", "message": "Solicitud inválida."}}
        )
