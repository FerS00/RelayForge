from __future__ import annotations

import json
import re
import stat
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

DESKTOP_KINDS = (
    "desktop_launch",
    "desktop_inspect",
    "desktop_invoke",
    "desktop_set_value",
    "desktop_type",
    "desktop_keys",
    "desktop_menu",
    "desktop_capture",
    "desktop_close",
)
KIND_OPERATION = {
    "desktop_inspect": "inspect",
    "desktop_invoke": "invoke",
    "desktop_set_value": "set_value",
    "desktop_type": "type_text",
    "desktop_keys": "keys",
    "desktop_menu": "menu",
    "desktop_capture": "capture",
    "desktop_close": "close",
}
_PATH_PATTERN = re.compile(r"[A-Za-z]:[\\/]|\\\\|/|\.\.")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class DesktopPolicyError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class Control(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    automation_id: str = Field(default="", max_length=256)
    name: str = Field(default="", max_length=256)
    control_type: str = Field(default="", max_length=64, pattern=r"^[A-Za-z]*$")

    @model_validator(mode="after")
    def not_empty(self) -> Control:
        if not (self.automation_id or self.name or self.control_type):
            raise ValueError("control_empty")
        return self


class InspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    depth: int = Field(default=3, ge=1, le=4)
    limit: int = Field(default=120, ge=1, le=200)


class ControlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    control: Control


class ValueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    control: Control
    value: str = Field(max_length=10_000)


class TypeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    control: Control | None = None
    text: str = Field(min_length=1, max_length=10_000)


class KeysRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    chord: Literal["ctrl+s", "ctrl+a", "enter", "tab", "escape", "alt+f4"]


class MenuRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(min_length=1, max_length=4)


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


_SCHEMAS: dict[str, type[BaseModel]] = {
    "desktop_inspect": InspectRequest,
    "desktop_invoke": ControlRequest,
    "desktop_set_value": ValueRequest,
    "desktop_type": TypeRequest,
    "desktop_keys": KeysRequest,
    "desktop_menu": MenuRequest,
    "desktop_capture": EmptyRequest,
    "desktop_close": EmptyRequest,
}


def parse_request(kind: str, raw: str) -> dict[str, Any]:
    schema = _SCHEMAS.get(kind)
    if schema is None:
        raise DesktopPolicyError("desktop_kind_invalid")
    try:
        data = json.loads(raw or "{}")
        parsed = schema.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        raise DesktopPolicyError("desktop_request_invalid") from None
    return parsed.model_dump(exclude_none=True)


def requires_path_approval(kind: str, request: dict[str, Any], allowed_dirs: tuple[Path, ...]) -> bool:
    """Text that looks like a path must be exactly one allowed path; it then needs approval."""
    value = request.get("value") if kind == "desktop_set_value" else request.get("text")
    if not isinstance(value, str) or not _PATH_PATTERN.search(value):
        return False
    candidate = Path(value.strip())
    if not candidate.is_absolute() or "\n" in value or ":" in candidate.name:
        raise DesktopPolicyError("desktop_path_rejected")
    if any(part in {".", ".."} for part in candidate.parts):
        raise DesktopPolicyError("desktop_path_rejected")
    for root in allowed_dirs:
        base = root.resolve()
        if not candidate.is_relative_to(base) or candidate == base:
            continue
        current = base
        for part in candidate.relative_to(base).parts:
            current = current / part
            try:
                info = current.lstat()
            except FileNotFoundError:
                break
            except OSError:
                raise DesktopPolicyError("desktop_path_rejected") from None
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & _REPARSE_POINT:
                raise DesktopPolicyError("desktop_path_rejected")
        return True
    raise DesktopPolicyError("desktop_path_rejected")
