from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.engine import Engine
from starlette.middleware.base import RequestResponseEndpoint

from relayforge.adapters.antigravity.adapter import AntigravityAdapter
from relayforge.adapters.claude.adapter import ClaudeAdapter
from relayforge.adapters.claude.orchestrator import ClaudeOrchestrator
from relayforge.adapters.codex.adapter import CodexAdapter
from relayforge.adapters.codex.planner import CodexPlanner
from relayforge.api.auth import (
    allowed_host,
    authenticated,
    csrf_is_valid,
    origin_is_valid,
    stream_origin_is_valid,
)
from relayforge.core.agent_health import AgentHealthService
from relayforge.core.approvals import ApprovalService
from relayforge.core.audit import Auditor, AuditWorkflow
from relayforge.core.auth import AuthService
from relayforge.core.chat import ChatService
from relayforge.core.checks import ChecksWorkflow
from relayforge.core.delivery import DeliveryWorkflow
from relayforge.core.events import EventBus
from relayforge.core.jobs import JobService
from relayforge.core.metrics import MetricsService
from relayforge.core.policy import PolicyEngine
from relayforge.core.repositories import RepositoryService
from relayforge.core.scheduler import JobScheduler
from relayforge.core.workflow import ImplementationWorkflow
from relayforge.core.workflows import WorkflowTemplates
from relayforge.db.session import create_db_engine, make_session_factory, run_migrations
from relayforge.git.delivery import GitDelivery
from relayforge.git.worktrees import WorktreeManager
from relayforge.process.supervisor import RunHandle, Supervisor
from relayforge.settings import Settings


def create_app(
    settings: Settings,
    *,
    db_path: Path | None = None,
    web_dist: Path | None = None,
    supervisor: Supervisor | None = None,
    engine: Engine | None = None,
    auditor: Auditor | None = None,
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
    jobs = JobService(
        make_session_factory(engine), bus, orchestrator, settings.workspace_dir, settings.home / "data"
    )

    def process_started(step_id: str, handle: RunHandle, agent: str) -> None:
        jobs.update_step_by_id(step_id, pid=handle.pid, pid_create_time=handle.create_time)
        jobs.record_turn(step_id, agent)

    orchestrator.on_process_started = lambda step_id, handle: process_started(step_id, handle, "claude")
    orchestrator.on_heartbeat = jobs.heartbeat_step
    orchestrator.on_usage = lambda step_id, usage: jobs.record_usage(step_id, "claude", usage)
    codex_planner = CodexPlanner(CodexAdapter(settings.codex_executable), supervisor, settings.home / "data")
    codex_planner.on_process_started = lambda step_id, handle: process_started(step_id, handle, "codex")
    codex_planner.on_heartbeat = jobs.heartbeat_step
    codex_planner.on_usage = lambda step_id, usage: jobs.record_usage(step_id, "codex", usage)
    jobs.planners["codex"] = codex_planner
    worktrees = WorktreeManager(settings.home / "worktrees")
    implementation = ImplementationWorkflow(
        jobs, CodexAdapter(settings.codex_executable), supervisor, worktrees, settings.home / "data"
    )
    checks = ChecksWorkflow(jobs, supervisor)
    audit_workflow = AuditWorkflow(jobs, auditor or AntigravityAdapter())
    approvals = ApprovalService(make_session_factory(engine))
    policy_path = Path(__file__).resolve().parents[3] / "config" / "policies" / "default.yaml"
    delivery = DeliveryWorkflow(
        jobs,
        approvals,
        PolicyEngine.load(policy_path),
        GitDelivery(approvals),
        settings.home / "data",
    )
    agent_health = AgentHealthService(make_session_factory(engine))
    workflows = WorkflowTemplates(Path(__file__).resolve().parents[3] / "config" / "workflows")
    scheduler = JobScheduler(
        jobs, implementation, checks, audit_workflow, delivery, agent_health, supervisor, workflows
    )
    repositories = RepositoryService(make_session_factory(engine), settings.projects_root)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        await application.state.job_scheduler.startup()
        yield
        await application.state.job_scheduler.shutdown()
        tasks = tuple(application.state.chat.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        application.state.supervisor.kill_all()
        application.state.engine.dispose()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.engine = engine
    app.state.settings = settings
    app.state.auth = AuthService(make_session_factory(engine))
    app.state.supervisor = supervisor
    app.state.chat = ChatService(make_session_factory(engine), bus, orchestrator, settings.workspace_dir)
    app.state.jobs = jobs
    app.state.job_scheduler = scheduler
    app.state.repositories = repositories
    app.state.approvals = approvals
    app.state.agent_health = agent_health
    app.state.agent_status_lock = threading.Lock()
    app.state.agent_status_cache = (float("-inf"), {})
    app.state.metrics = MetricsService(make_session_factory(engine))

    @app.middleware("http")
    async def security_headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not allowed_host(request, settings):
            return JSONResponse(
                status_code=400,
                content={"error": {"code": "invalid_host", "message": "Host no permitido.", "details": {}}},
            )
        path = request.url.path
        if path.startswith("/api/") and request.method not in {"GET", "HEAD", "OPTIONS"}:
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
            if not origin_is_valid(request):
                return JSONResponse(
                    status_code=403,
                    content={"error": {"code": "forbidden_origin", "message": "Origen no permitido."}},
                )
            if not csrf_is_valid(request):
                return JSONResponse(
                    status_code=403,
                    content={"error": {"code": "csrf_rejected", "message": "Token CSRF inválido."}},
                )
        if path == "/api/stream" and not stream_origin_is_valid(request):
            return JSONResponse(
                status_code=403,
                content={"error": {"code": "forbidden_origin", "message": "Origen no permitido."}},
            )
        public_paths = {"/api/auth/status", "/api/auth/csrf", "/api/auth/pair"}
        if (
            path.startswith("/api/")
            and path not in public_paths
            and not authenticated(request, settings, app.state.auth)
        ):
            return JSONResponse(
                status_code=401,
                content={"error": {"code": "authentication_required", "message": "Se requiere pairing."}},
            )
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "img-src 'self' data:; font-src 'self'; object-src 'none'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'"
        )
        return response

    from relayforge.api.routes.agents import router as agents_router
    from relayforge.api.routes.approvals import router as approvals_router
    from relayforge.api.routes.auth import router as auth_router
    from relayforge.api.routes.conversations import router as conversations_router
    from relayforge.api.routes.doctor import router as doctor_router
    from relayforge.api.routes.jobs import router as jobs_router
    from relayforge.api.routes.metrics import router as metrics_router
    from relayforge.api.routes.repositories import router as repositories_router
    from relayforge.api.routes.stream import router as stream_router

    app.include_router(auth_router)
    app.include_router(approvals_router)
    app.include_router(agents_router)
    app.include_router(conversations_router)
    app.include_router(doctor_router)
    app.include_router(jobs_router)
    app.include_router(metrics_router)
    app.include_router(repositories_router)
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
