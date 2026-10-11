from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from relayforge.desktop.policy import DESKTOP_KINDS
from relayforge.doctor.model_catalog import discover_efforts

EFFORTS: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")

KIND_TOOL: dict[str, str] = {
    "write_file": "write_files",
    "native_task": "commands",
    "development_job": "git_local",
    "start_preview": "preview",
    "stop_preview": "preview",
    **{kind: "desktop" for kind in DESKTOP_KINDS},
}

TOOL_LABELS: dict[str, str] = {
    "write_files": "write_file (texto)",
    "commands": "native_task (archivos/comandos locales)",
    "git_local": "development_job (software en repo registrado)",
    "preview": "start_preview/stop_preview",
}


class ConversationSettingsError(ValueError):
    def __init__(self, code: str, details: dict[str, Any] | None = None) -> None:
        self.code = code
        self.details = details or {}
        super().__init__(code)


class ToolPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    write_files: bool = True
    commands: bool = True
    git_local: bool = True
    preview: bool = True
    desktop: bool = True
    web_search: bool = False
    remote_delivery: bool = False


DEFAULT_TOOLS_JSON = json.dumps(ToolPolicy().model_dump(), sort_keys=True, separators=(",", ":"))


def load_tools(raw: str | None) -> ToolPolicy:
    """Stored policies are trusted rows; missing keys fall back to the defaults."""
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    defaults = ToolPolicy().model_dump()
    return ToolPolicy(**{key: bool(data.get(key, value)) for key, value in defaults.items()})


def dump_tools(policy: ToolPolicy) -> str:
    return json.dumps(policy.model_dump(), sort_keys=True, separators=(",", ":"))


def merge_tools(current: ToolPolicy, changes: dict[str, Any]) -> ToolPolicy:
    try:
        merged = ToolPolicy.model_validate({**current.model_dump(), **changes})
    except ValidationError:
        raise ConversationSettingsError("tools_invalid") from None
    if merged.remote_delivery and not merged.git_local:
        raise ConversationSettingsError("tool_dependency", {"remote_delivery": "git_local"})
    return merged


def supported_efforts(
    agent: str, model: str, catalog: dict[str, tuple[str, ...]] | None = None
) -> tuple[str, ...]:
    if agent == "claude":
        return EFFORTS
    if agent != "codex":
        return ()
    levels = (catalog if catalog is not None else discover_efforts("codex")).get(model)
    if not levels:
        return EFFORTS
    return tuple(level for level in EFFORTS if level in levels)


def tool_disabled(policy: ToolPolicy, kind: str) -> str | None:
    key = KIND_TOOL.get(kind)
    if key is None:
        return None
    return None if getattr(policy, key) else key
