from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml

Decision = Literal["allow", "ask", "deny"]


@dataclass(frozen=True)
class PolicyOperation:
    agent: str
    role: str
    repo: str
    workflow: str
    tool: str
    operation: str
    target: str
    risk: str = "normal"
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    reason: str
    workflow: str


_PROTECTED = {"git.force_push", "git.merge", "git.push_protected_branch"}
_DECISIONS = {"allow", "ask", "deny"}


class PolicyError(ValueError):
    pass


class PolicyEngine:
    def __init__(self, document: dict[str, object]) -> None:
        if document.get("version") != 1:
            raise PolicyError("Versión de política no soportada.")
        for key in ("defaults", "profiles", "workflows"):
            if not isinstance(document.get(key), dict):
                raise PolicyError(f"Sección inválida: {key}.")
        defaults = document["defaults"]
        assert isinstance(defaults, dict)
        self._validate_layer(defaults, "defaults")
        for section in ("profiles", "workflows"):
            entries = document[section]
            assert isinstance(entries, dict)
            for name, layer in entries.items():
                if not isinstance(name, str) or not isinstance(layer, dict):
                    raise PolicyError(f"Entrada inválida en {section}.")
                self._validate_layer(layer, f"{section}.{name}")
        escalations = document.get("path_escalations", [])
        if not isinstance(escalations, list) or any(
            not isinstance(row, dict)
            or not isinstance(row.get("pattern"), str)
            or not isinstance(row.get("workflow"), str)
            for row in escalations
        ):
            raise PolicyError("path_escalations debe contener pattern y workflow de texto.")
        overrides = document.get("overrides", [])
        if not isinstance(overrides, list) or any(not isinstance(row, dict) for row in overrides):
            raise PolicyError("overrides debe ser una lista de objetos.")
        for index, row in enumerate(overrides):
            assert isinstance(row, dict)
            for selector in ("agent", "role", "repo", "workflow", "tool", "operation", "target", "risk"):
                if selector in row and not isinstance(row[selector], str):
                    raise PolicyError(f"Matcher inválido en overrides[{index}].")
            self._validate_layer(
                {
                    key: value
                    for key, value in row.items()
                    if key not in {"agent", "role", "repo", "workflow", "tool", "operation", "target", "risk"}
                },
                f"overrides[{index}]",
            )
        self.document = document

    @staticmethod
    def _validate_layer(layer: dict[object, object], label: str) -> None:
        if any(
            not isinstance(key, str) or not isinstance(value, str) or value not in _DECISIONS
            for key, value in layer.items()
        ):
            raise PolicyError(f"Decisión inválida en {label}.")

    @classmethod
    def load(cls, path: Path) -> PolicyEngine:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise PolicyError("No se pudo cargar la política.") from exc
        if not isinstance(raw, dict):
            raise PolicyError("La política debe ser un objeto YAML.")
        return cls(raw)

    @staticmethod
    def normalize(value: str) -> str:
        return "/".join(part for part in value.replace("\\", "/").strip().split("/") if part).casefold()

    def evaluate(self, operation: PolicyOperation, *, profile: str = "default") -> PolicyResult:
        workflow = operation.workflow
        normalized_paths = tuple(self.normalize(path) for path in operation.paths)
        escalations = self.document.get("path_escalations", [])
        if isinstance(escalations, list):
            for row in escalations:
                if (
                    isinstance(row, dict)
                    and isinstance(row.get("pattern"), str)
                    and any(
                        fnmatch.fnmatchcase(path, self.normalize(row["pattern"])) for path in normalized_paths
                    )
                ):
                    candidate = row.get("workflow")
                    if isinstance(candidate, str):
                        workflow = candidate
        if operation.operation in _PROTECTED:
            return PolicyResult("deny", "La operación está denegada de forma incondicional.", workflow)

        layers: list[dict[str, object]] = []
        defaults = self.document.get("defaults", {})
        profiles = self.document.get("profiles", {})
        workflows = self.document.get("workflows", {})
        if isinstance(defaults, dict):
            layers.append(defaults)
        if isinstance(profiles, dict) and isinstance(profiles.get(profile), dict):
            layers.append(profiles[profile])
        if isinstance(workflows, dict) and isinstance(workflows.get(workflow), dict):
            layers.append(workflows[workflow])
        overrides = self.document.get("overrides", [])
        if isinstance(overrides, list):
            layers.extend(row for row in overrides if isinstance(row, dict) and self._matches(row, operation))
        values = [layer.get(operation.operation) for layer in layers if operation.operation in layer]
        if any(value not in _DECISIONS for value in values):
            raise PolicyError("Decisión inválida en la política.")
        if "deny" in values:
            return PolicyResult("deny", "Una capa de política denegó la operación.", workflow)
        if values:
            return PolicyResult(values[-1], "Decisión de la capa más específica.", workflow)  # type: ignore[arg-type]
        return PolicyResult("ask", "Sin regla explícita, se requiere aprobación.", workflow)

    def _matches(self, row: dict[str, object], operation: PolicyOperation) -> bool:
        for field in ("agent", "role", "repo", "workflow", "tool", "operation", "target", "risk"):
            matcher = row.get(field)
            if matcher is not None and not fnmatch.fnmatchcase(
                self.normalize(str(getattr(operation, field))), self.normalize(str(matcher))
            ):
                return False
        return True
