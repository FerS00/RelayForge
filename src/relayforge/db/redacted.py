from __future__ import annotations

from typing import Any

from sqlalchemy import Text
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from relayforge.security.redact import redact_json_text, redact_text


class RedactedText(TypeDecorator[str]):
    """Redact content on database writes and again when reading legacy rows."""

    impl = Text
    cache_ok = True

    def __init__(self, *, json_content: bool = False) -> None:
        super().__init__()
        self.json_content = json_content

    def process_bind_param(self, value: str | None, dialect: Dialect) -> str | None:
        del dialect
        if value is None:
            return None
        return redact_json_text(value) if self.json_content else redact_text(value)

    def process_result_value(self, value: Any, dialect: Dialect) -> str | None:
        del dialect
        if value is None:
            return None
        text = str(value)
        return redact_json_text(text) if self.json_content else redact_text(text)
