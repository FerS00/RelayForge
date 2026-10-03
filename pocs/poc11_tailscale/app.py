"""Servidor local para medir identidad de Tailscale Serve y estabilidad SSE."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.redact import redact  # noqa: E402

IDENTITY_HEADERS = ("tailscale-user-login", "tailscale-user-name", "tailscale-user-profile-pic",
                    "host", "origin", "x-forwarded-for", "x-forwarded-proto")
PAGE = """<!doctype html><html lang="es"><meta charset="utf-8"><title>POC-11 Tailscale</title>
<h1>POC-11 Tailscale Serve</h1><pre id="identity">Cargando identidad…</pre>
<p>Eventos SSE: <span id="count">0</span>; reconexiones: <span id="reconnects">0</span>;
última marca: <span id="last">—</span></p><script>
fetch('/whoami').then(r=>r.json()).then(v=>document.querySelector('#identity').textContent=
JSON.stringify(v,null,2));let n=0,re=0,seen=false;const s=new EventSource('/sse');
s.onopen=()=>{if(seen)re++;seen=true;document.querySelector('#reconnects').textContent=re};
s.onerror=()=>{};s.addEventListener('tick',e=>{n++;document.querySelector('#count').textContent=n;
document.querySelector('#last').textContent=JSON.parse(e.data).ts});</script></html>"""


def _identity(request: Request) -> dict:
    headers = request.headers
    return {"Tailscale-User-Login": headers.get("tailscale-user-login"),
            "Tailscale-User-Name": headers.get("tailscale-user-name"),
            "Tailscale-User-Profile-Pic": bool(headers.get("tailscale-user-profile-pic")),
            "Host": headers.get("host"), "Origin": headers.get("origin"),
            "X-Forwarded-For": headers.get("x-forwarded-for"),
            "X-Forwarded-Proto": headers.get("x-forwarded-proto"),
            "client.host": request.client.host if request.client else None}


def create_app(log_path: Path, sse_minutes: float = 15) -> FastAPI:
    app = FastAPI(title="RelayForge POC-11")

    @app.middleware("http")
    async def log_request(request: Request, call_next):
        response = await call_next(request)
        row = {"path": request.url.path, **_identity(request),
               "ts": datetime.now(timezone.utc).isoformat()}
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(redact(json.dumps(row, ensure_ascii=False)) + "\n")
        return response

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return PAGE

    @app.get("/whoami")
    async def whoami(request: Request) -> dict:
        return _identity(request)

    @app.get("/sse")
    async def sse(request: Request):
        try:
            start = max(0, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            start = 0

        async def events():
            deadline = time.monotonic() + max(0, sse_minutes) * 60
            number = start + 1
            next_ping = time.monotonic() + 15
            while time.monotonic() < deadline:
                if await request.is_disconnected():
                    break
                stamp = datetime.now(timezone.utc).isoformat()
                yield f"id: {number}\nevent: tick\ndata: {json.dumps({'n': number, 'ts': stamp})}\n\n"
                number += 1
                now = time.monotonic()
                if now >= next_ping:
                    yield ": ping\n\n"
                    next_ping = now + 15
                await asyncio.sleep(min(1, max(0, deadline - now)))

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8792)
    parser.add_argument("--log", type=Path, default=Path("poc11_tailscale.ndjson"))
    parser.add_argument("--sse-minutes", type=float, default=15)
    args = parser.parse_args(argv)
    uvicorn.run(create_app(args.log, args.sse_minutes), host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
