from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from relayforge.core.metrics import MetricsService, parse_metric_date

router = APIRouter(prefix="/api/metrics")


@router.get("/summary", response_model=None)
def metrics_summary(
    request: Request, from_: str | None = Query(default=None, alias="from"), to: str | None = None
) -> dict[str, object] | JSONResponse:
    try:
        start = parse_metric_date(from_)
        end = parse_metric_date(to)
    except ValueError as exc:
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_date", "message": str(exc)}})
    if start is not None and end is not None and start >= end:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "invalid_range", "message": "El inicio debe ser anterior al fin."}},
        )
    return cast(MetricsService, request.app.state.metrics).summary(start, end)
