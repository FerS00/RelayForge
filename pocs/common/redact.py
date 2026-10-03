"""Redacción de secretos conocidos y rutas de perfil en evidencia."""

from __future__ import annotations

import os
import re

_EMAIL = re.compile(
    r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+\b"
)
_ACCOUNT_JSON = re.compile(
    r'("(?:orgId|orgName|accountId|email)"\s*:\s*)"(?:\\.|[^"\\])*"', re.IGNORECASE
)
_ESCAPED_ACCOUNT_JSON = re.compile(
    r'(\\"(?:orgId|orgName|accountId|email)\\"\s*:\s*)\\"(?:\\\\.|[^"\\])*\\"',
    re.IGNORECASE,
)

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-[A-Za-z0-9_-]{16,}"), "secret_key"),
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "github_token"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "github_pat"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "aws_key"),
    (re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}"), "slack_token"),
    (re.compile(r"eyJ[\w-]+\.[\w-]+\.[\w-]+"), "jwt"),
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.DOTALL,
        ),
        "private_key",
    ),
    (
        re.compile(r"(?i)\b(token|secret|password|api[_-]?key)(\s*[:=]\s*)(\S{8,})"),
        "credential",
    ),
)


def redact(text: str) -> str:
    result = text
    result = _ACCOUNT_JSON.sub(r'\1"[REDACTED:account]"', result)
    result = _ESCAPED_ACCOUNT_JSON.sub(r'\1\\"[REDACTED:account]\\"', result)
    result = _EMAIL.sub("[REDACTED:email]", result)
    for pattern, kind in _PATTERNS:
        if kind == "credential":
            result = pattern.sub(lambda match: f"{match.group(1)}{match.group(2)}[REDACTED:{kind}]", result)
        else:
            result = pattern.sub(f"[REDACTED:{kind}]", result)

    profiles = {os.environ.get("USERPROFILE"), os.environ.get("HOME")}
    for profile in sorted((item for item in profiles if item and len(item) > 3), key=len, reverse=True):
        pattern = r"[/\\]".join(re.escape(part) for part in re.split(r"[/\\]", profile))
        result = re.sub(pattern, "~", result, flags=re.IGNORECASE)
    return result
