from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Request

from relayforge.doctor.checks import doctor_report
from relayforge.settings import Settings

router = APIRouter(prefix="/api/doctor")


@router.get("")
def get_doctor(request: Request) -> dict[str, object]:
    return doctor_report(cast(Settings, request.app.state.settings), request.app.state.engine)
