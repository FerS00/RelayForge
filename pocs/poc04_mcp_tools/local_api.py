"""API loopback mínima protegida por un token efímero."""

from __future__ import annotations

import argparse
import hmac
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def create_app(token: str, log_path: Path) -> FastAPI:
    app = FastAPI()
    counter = 0
    lock = Lock()

    @app.middleware("http")
    async def authenticate_and_log(request: Request, call_next):
        nonlocal counter
        auth = request.headers.get("authorization", "")
        supplied = auth[7:] if auth.lower().startswith("bearer ") else ""
        auth_ok = bool(supplied) and hmac.compare_digest(supplied, token)
        body = await request.body()
        body_sent = False

        async def replay_body() -> dict:
            nonlocal body_sent
            if body_sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        request._receive = replay_body
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {}
        body_keys = sorted(parsed) if isinstance(parsed, dict) else []
        if request.url.path.startswith("/internal/") and not auth_ok:
            response = JSONResponse(status_code=401, content={"detail": "Unauthorized"})
        else:
            response = await call_next(request)
        row = {"ts": datetime.now(timezone.utc).isoformat(), "path": request.url.path,
               "status": response.status_code, "auth_ok": auth_ok, "body_keys": body_keys}
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with lock, log_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        return response

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/internal/mcp/get_job_status")
    def get_job_status(payload: dict) -> JSONResponse:
        if payload.get("job_id") != "JOB-000001":
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        return JSONResponse({"job_id": "JOB-000001", "status": "IMPLEMENTING", "iteration": 1})

    @app.post("/internal/mcp/propose_job")
    def propose_job(payload: dict) -> dict:
        nonlocal counter
        with lock:
            counter += 1
            proposal = counter
        return {"proposal_id": f"PROP-{proposal}", "state": "PENDING_USER_CONFIRMATION"}

    return app


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--log", type=Path, required=True)
    args = parser.parse_args()
    token = args.token_file.read_text(encoding="utf-8").strip()
    uvicorn.run(create_app(token, args.log), host="127.0.0.1", port=args.port, log_config=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
