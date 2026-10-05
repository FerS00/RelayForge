from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class WorkflowConfigError(ValueError):
    pass


@dataclass(frozen=True)
class WorkflowTemplate:
    name: str
    checks: bool
    audit: bool
    plan_approval: str
    audit_profile: str
    max_iterations: int


class WorkflowTemplates:
    _names = {"trivial", "feature", "security"}

    def __init__(self, root: Path) -> None:
        self.root = root
        self._templates = {name: self._load(name) for name in self._names}

    def _load(self, name: str) -> WorkflowTemplate:
        path = self.root / f"{name}.yaml"
        try:
            value: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise WorkflowConfigError(f"workflow_template_invalid:{name}") from exc
        if (
            not isinstance(value, dict)
            or set(value)
            != {"version", "checks", "audit", "plan_approval", "audit_profile", "max_iterations"}
            or isinstance(value.get("version"), bool)
            or value.get("version") != 1
            or not isinstance(value.get("checks"), bool)
            or not isinstance(value.get("audit"), bool)
            or value.get("plan_approval") not in {"never", "ask"}
            or value.get("audit_profile") not in {"default", "security"}
            or not isinstance(value.get("max_iterations"), int)
            or isinstance(value.get("max_iterations"), bool)
            or not 1 <= value["max_iterations"] <= 3
        ):
            raise WorkflowConfigError(f"workflow_template_invalid:{name}")
        return WorkflowTemplate(
            name,
            value["checks"],
            value["audit"],
            value["plan_approval"],
            value["audit_profile"],
            value["max_iterations"],
        )

    def resolve(self, requested: str, suggested: str) -> WorkflowTemplate:
        selected = "security" if suggested == "security" else suggested if requested == "auto" else requested
        if selected not in self._templates:
            raise WorkflowConfigError("workflow_selection_invalid")
        return self._templates[selected]

    def for_job(self, name: str) -> WorkflowTemplate:
        if name not in self._templates:
            raise WorkflowConfigError("workflow_selection_invalid")
        return self._templates[name]

    def elevate_for_paths(self, current: str, paths: list[str]) -> WorkflowTemplate:
        sensitive = any(
            any(part in {"auth", "security"} for part in path.replace("\\", "/").casefold().split("/"))
            for path in paths
        )
        selected = "security" if sensitive else current
        if selected not in self._templates:
            selected = "feature"
        return self._templates[selected]
