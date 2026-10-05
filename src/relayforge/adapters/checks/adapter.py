from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from relayforge.adapters.base import LaunchPlan

_ALLOWED_ENV = ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC")
_SHELLS = {
    "cmd",
    "cmd.exe",
    "powershell",
    "powershell.exe",
    "pwsh",
    "pwsh.exe",
    "sh",
    "bash",
    "zsh",
    "wscript",
    "cscript",
}
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}$")
_JUNIT_ARG = re.compile(r"^--junit(?:xml|-xml)=(.+)$")
_MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_MAX_JUNIT_BYTES = 2 * 1024 * 1024


class ChecksValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CheckCommand:
    name: str
    argv: tuple[str, ...]
    timeout_seconds: int = 600

    @classmethod
    def parse(cls, value: Any) -> CheckCommand:
        if not isinstance(value, dict) or set(value) - {"name", "argv", "timeout_seconds"}:
            raise ChecksValidationError("La definición del check no tiene el formato permitido.")
        name = value.get("name")
        argv = value.get("argv")
        timeout = value.get("timeout_seconds", 600)
        if not isinstance(name, str) or _NAME.fullmatch(name) is None:
            raise ChecksValidationError("El nombre del check debe tener 1–80 caracteres permitidos.")
        if not isinstance(argv, list) or not 1 <= len(argv) <= 64:
            raise ChecksValidationError("argv debe contener entre 1 y 64 argumentos.")
        if any(not isinstance(item, str) or not item or "\0" in item for item in argv):
            raise ChecksValidationError("argv contiene un argumento inválido.")
        if sum(len(item) for item in argv) > 4096:
            raise ChecksValidationError("argv supera 4096 caracteres.")
        executable = argv[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        if executable in _SHELLS:
            raise ChecksValidationError("No se permiten intérpretes de shell como check.")
        lowered = [item.lower() for item in argv]
        if executable in {"pip", "pip.exe", "pip3", "pip3.exe"} and "install" in lowered[1:]:
            raise ChecksValidationError("Los checks no pueden instalar dependencias.")
        if executable in {"npm", "npm.cmd", "pnpm", "pnpm.cmd"} and any(
            token in lowered[1:] for token in {"install", "ci", "add"}
        ):
            raise ChecksValidationError("Los checks no pueden instalar dependencias.")
        if executable in {"uv", "uv.exe"} and lowered[1:2] == ["pip"] and "install" in lowered[2:]:
            raise ChecksValidationError("Los checks no pueden instalar dependencias.")
        if (
            executable in {"python", "python.exe", "python3", "python3.exe"}
            and lowered[1:3]
            == [
                "-m",
                "pip",
            ]
            and lowered[3:4] == ["install"]
        ):
            raise ChecksValidationError("Los checks no pueden instalar dependencias.")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 3600:
            raise ChecksValidationError("timeout_seconds debe estar entre 1 y 3600.")
        return cls(name, tuple(argv), timeout)

    def json(self) -> dict[str, Any]:
        return {"name": self.name, "argv": list(self.argv), "timeout_seconds": self.timeout_seconds}


class ChecksAdapter:
    @staticmethod
    def parse_many(value: Any) -> list[CheckCommand]:
        if not isinstance(value, list) or len(value) > 32:
            raise ChecksValidationError("check_commands debe ser una lista de hasta 32 elementos.")
        parsed = [CheckCommand.parse(item) for item in value]
        if len({item.name.casefold() for item in parsed}) != len(parsed):
            raise ChecksValidationError("Los nombres de los checks deben ser únicos.")
        return parsed

    @staticmethod
    def build_run(
        command: CheckCommand, cwd: Path, *, source_env: dict[str, str] | None = None
    ) -> LaunchPlan:
        root = cwd.resolve(strict=True)
        if not root.is_dir():
            raise ChecksValidationError("El worktree del check no es un directorio.")
        source = os.environ if source_env is None else source_env
        env = {key: source[key] for key in _ALLOWED_ENV if key in source}
        return LaunchPlan(argv=command.argv, cwd=root, stdin_text="", env=env)

    @staticmethod
    def summarize_output(output: str) -> dict[str, int] | None:
        matches = list(
            re.finditer(
                r"(?P<counts>(?:\d+\s+(?:passed|failed|error|errors|skipped|xfailed|xpassed|deselected)\b[^\n]*,?\s*)+)",
                output,
                re.I,
            )
        )
        if not matches:
            return None
        counts: dict[str, int] = {"passed": 0, "failed": 0, "skipped": 0}
        last_line = matches[-1].group("counts")
        for value, label in re.findall(
            r"(\d+)\s+(passed|failed|error|errors|skipped|xfailed|xpassed)\b", last_line, re.I
        ):
            key = "failed" if label.lower() in {"error", "errors"} else label.lower()
            if key in counts:
                counts[key] += int(value)
        return counts

    @staticmethod
    def junit_counts(worktree: Path, argv: tuple[str, ...]) -> dict[str, int] | None:
        target: Path | None = None
        for argument in argv:
            match = _JUNIT_ARG.fullmatch(argument)
            if match:
                candidate = (worktree / match.group(1)).resolve(strict=False)
                if candidate.is_relative_to(worktree.resolve()):
                    target = candidate
                break
        if target is None:
            return None
        try:
            if target.stat().st_size > _MAX_JUNIT_BYTES:
                return None
            raw = target.read_bytes()
            if re.search(rb"<!\s*(?:DOCTYPE|ENTITY)", raw, re.I):
                return None
            root = ET.fromstring(raw)
        except (OSError, ET.ParseError):
            return None
        suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
        if not suites:
            return None
        totals = {"passed": 0, "failed": 0, "skipped": 0}
        for suite in suites:
            try:
                tests = int(suite.attrib.get("tests", "0"))
                failures = int(suite.attrib.get("failures", "0")) + int(suite.attrib.get("errors", "0"))
                skipped = int(suite.attrib.get("skipped", "0"))
            except ValueError:
                return None
            totals["passed"] += max(0, tests - failures - skipped)
            totals["failed"] += failures
            totals["skipped"] += skipped
        return totals


def parse_commands_json(raw: str) -> list[CheckCommand]:
    try:
        return ChecksAdapter.parse_many(json.loads(raw))
    except json.JSONDecodeError as exc:
        raise ChecksValidationError("check_commands no contiene JSON válido.") from exc
