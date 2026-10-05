from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_SECRET_VALUE_KEYS = re.compile(
    r"^(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|passwd|"
    r"secret|authorization|token|credential|private[_-]?key|secret[_-]?key|subscription[_-]?key)$",
    re.IGNORECASE,
)
_LABELED_SECRET = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|passwd|"
    r"secret|authorization|token|credential|private[_-]?key|secret[_-]?key|subscription[_-]?key)[\"']?\s*[:=]\s*[\"']?)([^\s\"',;}\]]+)([\"']?)"
)
_SECRET_PATTERNS = (
    re.compile(
        r"\b(?:sk-[A-Za-z0-9_-]{20,}|sk_(?:live|test)_[A-Za-z0-9]{16,}|"
        r"gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
        r"glpat-[A-Za-z0-9_-]{20,}|npm_[A-Za-z0-9]{30,}|pypi-[A-Za-z0-9_-]{40,}|"
        r"AIza[0-9A-Za-z_-]{35})\b"
    ),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?"
        r"-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
        re.DOTALL,
    ),
)
_PERSONAL_PATHS = (
    re.compile(r"(?i)\b[A-Z]:\\Users\\[^\\/\s\"'<>]+(?:\\[^\s\"'<>]*)?"),
    re.compile(r"(?i)(?<![\w/])(?:/Users|/home|/root)/[^/\s\"'<>]+(?:/[^\s\"'<>]*)?"),
)
_STREAM_TAIL = 512


def redact_text(value: str) -> str:
    """Redact common credentials and account-specific home paths in text."""
    result = value
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub("[REDACTED]", result)
    result = _LABELED_SECRET.sub(r"\1[REDACTED]\3", result)
    for pattern in _PERSONAL_PATHS:
        result = pattern.sub("[USER_PATH]", result)
    return result


class StreamingRedactor:
    """Hold a short text tail so a credential split across chunks is not emitted."""

    def __init__(self) -> None:
        self._pending = ""

    def push(self, fragment: str) -> str:
        self._pending += fragment
        split_at = len(self._pending) - _STREAM_TAIL
        if split_at <= 0:
            return ""
        boundary = max(
            self._pending.rfind(" ", 0, split_at),
            self._pending.rfind("\n", 0, split_at),
            self._pending.rfind("\t", 0, split_at),
        )
        if boundary < 0:
            return ""
        safe, self._pending = self._pending[: boundary + 1], self._pending[boundary + 1 :]
        return redact_text(safe)

    def finish(self) -> str:
        pending, self._pending = self._pending, ""
        return redact_text(pending)


def redact_value(value: Any) -> Any:
    """Recursively redact strings and values stored under secret-like JSON keys."""
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if isinstance(key, str) and _SECRET_VALUE_KEYS.fullmatch(key)
            else redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    return value


def redact_json_text(value: str) -> str:
    """Redact JSON string values while retaining valid JSON when possible."""
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return redact_text(value)
    return json.dumps(redact_value(parsed), ensure_ascii=False, separators=(",", ":"))


def redact_log_file(path: Path) -> None:
    """Redact a completed text or JSONL log in place, preserving record boundaries."""
    source = path.read_text(encoding="utf-8", errors="replace")
    records: list[Any] = []
    for line in source.splitlines():
        try:
            records.append(redact_value(json.loads(line)))
        except json.JSONDecodeError:
            records.append(redact_text(line))

    fragments: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def redact_fragments() -> None:
        if not fragments:
            return
        combined = "".join(str(delta.get("text", "")) for _, delta in fragments)
        if redact_text(combined) != combined:
            for _, delta in fragments:
                delta["text"] = "[REDACTED]"
        fragments.clear()

    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("type") != "stream_event" or not isinstance(record.get("event"), dict):
            continue
        event = record["event"]
        if event.get("type") == "message_start":
            redact_fragments()
        elif event.get("type") == "content_block_delta":
            delta = event.get("delta")
            if isinstance(delta, dict) and delta.get("type") == "text_delta":
                fragments.append((record, delta))
        elif event.get("type") == "message_stop":
            redact_fragments()
    redact_fragments()

    serialized = [
        json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        if isinstance(record, (dict, list))
        else str(record)
        for record in records
    ]
    path.write_text("\n".join(serialized) + ("\n" if source.endswith("\n") else ""), encoding="utf-8")
