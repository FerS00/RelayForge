from __future__ import annotations

import time
from typing import Any, cast

from fastapi import APIRouter, Request

from relayforge.core.agent_health import AgentHealthService
from relayforge.core.conversation_settings import EFFORTS
from relayforge.doctor.checks import _agent
from relayforge.doctor.model_catalog import discover_efforts, discover_models

router = APIRouter(prefix="/api/agents")


@router.get("")
def list_agents(request: Request) -> list[dict[str, str | None]]:
    return cast(AgentHealthService, request.app.state.agent_health).list()


@router.get("/status")
def agent_status(request: Request) -> list[dict[str, Any]]:
    service = cast(AgentHealthService, request.app.state.agent_health)
    settings = request.app.state.settings
    with request.app.state.agent_status_lock:
        now = time.monotonic()
        cached_at, probes = request.app.state.agent_status_cache
        if now - cached_at >= 30:
            probes = {
                "claude": _agent(settings.claude_executable, ["auth", "status"]),
                "codex": _agent(settings.codex_executable, ["login", "status"]),
                "antigravity": _agent("agy"),
            }
            for agent, executable in (
                ("claude", settings.claude_executable),
                ("codex", settings.codex_executable),
                ("antigravity", "agy"),
            ):
                probes[agent]["model_catalog"] = discover_models(agent, executable)
            probes["codex"]["effort_catalog"] = discover_efforts("codex")
            request.app.state.agent_status_cache = (now, probes)
    health = {row["agent"]: row for row in service.list()}
    result = []
    for agent, probe in probes.items():
        models = list(dict.fromkeys([*probe.get("model_catalog", []), *settings.agent_models.get(agent, ())]))
        if agent == "claude" and settings.claude_model and settings.claude_model not in models:
            models.insert(0, settings.claude_model)
        result.append(
            {
                "agent": agent,
                **{
                    key: value
                    for key, value in probe.items()
                    if key not in {"model_catalog", "effort_catalog"}
                },
                "health": health.get(agent),
                "models": models,
                "efforts": {
                    model: [level for level in EFFORTS if level in levels]
                    for model, levels in probe.get("effort_catalog", {}).items()
                },
                "default_efforts": list(EFFORTS) if agent in {"claude", "codex"} else [],
                "usage": service.usage(agent),
            }
        )
    return result
