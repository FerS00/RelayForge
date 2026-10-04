from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import Engine
from starlette.middleware.base import RequestResponseEndpoint

from relayforge.adapters.claude.adapter import ClaudeAdapter
from relayforge.adapters.claude.orchestrator import ClaudeOrchestrator
from relayforge.core.chat import ChatService
from relayforge.core.events import EventBus
from relayforge.db.session import create_db_engine, make_session_factory, run_migrations
from relayforge.process.supervisor import Supervisor
from relayforge.settings import Settings


def create_app(
    settings: Settings,
    *,
    db_path: Path | None = None,
    web_dist: Path | None = None,
    supervisor: Supervisor | None = None,
    engine: Engine | None = None,
) -> FastAPI:
    database = db_path or settings.home / "relayforge.db"
    distribution = web_dist or Path(__file__).resolve().parents[3] / "web" / "dist"
    if engine is None:
        database.parent.mkdir(parents=True, exist_ok=True)
        run_migrations(database)
        engine = create_db_engine(database)
    supervisor = supervisor or Supervisor()
    bus = EventBus()
    adapter = ClaudeAdapter(settings.claude_executable, settings.claude_model)
    orchestrator = ClaudeOrchestrator(adapter, supervisor, settings.home / "data")

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        yield
        tasks = tuple(application.state.chat.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        application.state.supervisor.kill_all()
        application.state.engine.dispose()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.engine = engine
    app.state.supervisor = supervisor
    app.state.chat = ChatService(make_session_factory(engine), bus, orchestrator, settings.workspace_dir)

    @app.middleware("http")
    async def security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
        host = request.headers.get("host", "")
        hostname = urlsplit(f"//{host}").hostname
        if hostname not in {"127.0.0.1", "localhost"}:
            return JSONResponse(
                status_code=400,
                content={"error": {"code": "invalid_host", "message": "Host no permitido.", "details": {}}},
            )
        if request.method == "POST" and request.url.path.startswith("/api/"):
            content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                return JSONResponse(
                    status_code=415,
                    content={
                        "error": {
                            "code": "unsupported_media_type",
                            "message": "Se requiere application/json.",
                            "details": {},
                        }
                    },
                )
            origin = request.headers.get("origin")
            if origin:
                origin_url = urlsplit(origin)
                expected_origin = f"{request.url.scheme}://{host}"
                if origin_url.scheme not in {"http", "https"} or origin.rstrip("/") != expected_origin:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "error": {
                                "code": "forbidden_origin",
                                "message": "Origen no permitido.",
                                "details": {},
                            }
                        },
                    )
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'self'"
        return response

    from relayforge.api.routes.conversations import router as conversations_router
    from relayforge.api.routes.stream import router as stream_router

    app.include_router(conversations_router)
    app.include_router(stream_router)

    @app.get("/")
    async def index() -> Response:
        index_file = distribution / "index.html"
        if not index_file.is_file():
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "code": "web_unavailable",
                        "message": "Compila la web con npm --prefix web run build.",
                        "details": {},
                    }
                },
            )
        return FileResponse(index_file)

    assets = distribution / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    return app
