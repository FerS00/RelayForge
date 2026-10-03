"""Pequeña interfaz local para observar Claude stream-json por SSE."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Iterator

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse

from common.binaries import locate
from common.evidence import Evidence
from common.procs import JobObject, spawn_in_job
from common.redact import redact

app = FastAPI()
PAGE = """<!doctype html><meta charset='utf-8'><title>Claude stream</title>
<textarea id='prompt'></textarea><button onclick='start()'>Enviar</button><pre id='out'></pre>
<script>function start(){const p=document.querySelector('#prompt').value;const e=new EventSource('/stream?prompt='+encodeURIComponent(p));
e.onmessage=x=>document.querySelector('#out').textContent+=x.data+'\\n';}</script>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE


@app.get("/stream")
def stream(prompt: str = Query(...), session: str | None = None) -> StreamingResponse:
    def events() -> Iterator[str]:
        binary = locate("claude")
        if binary.path is None:
            yield 'data: {"error":"claude no localizado"}\n\n'
            return
        evidence = Evidence("poc01-ui")
        prompt_file = evidence.write_text("prompt.txt", prompt)
        session_id = session or str(uuid.uuid4())
        command = [str(binary.path), "-p", "--output-format", "stream-json"]
        command.extend(["--resume", session] if session else ["--session-id", session_id])
        output = evidence.dir / "stream.ndjson"
        offset = 0
        last_ping = time.monotonic()
        try:
            with JobObject() as job:
                process = spawn_in_job(command, job, Path.cwd(), output, evidence.dir / "stderr.txt", prompt_file)
                while process.poll() is None or output.exists():
                    if output.exists():
                        with output.open("rb") as file:
                            file.seek(offset)
                            chunk = file.read()
                            offset = file.tell()
                        for line in chunk.decode("utf-8", errors="replace").splitlines():
                            yield f"data: {redact(line)}\n\n"
                    if time.monotonic() - last_ping >= 15:
                        yield ": ping\n\n"
                        last_ping = time.monotonic()
                    if process.poll() is not None and (not output.exists() or offset >= output.stat().st_size):
                        break
                    time.sleep(0.1)
        finally:
            if output.exists():
                evidence.write_text(output.name, output.read_text(encoding="utf-8", errors="replace"))
            stderr = evidence.dir / "stderr.txt"
            if stderr.exists():
                evidence.write_text(stderr.name, stderr.read_text(encoding="utf-8", errors="replace"))
    return StreamingResponse(events(), media_type="text/event-stream")
