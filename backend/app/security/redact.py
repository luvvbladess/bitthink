"""Strip secrets from logs, stored messages, and model-facing leftovers."""

from __future__ import annotations

import re
from typing import Any, Iterable

SECRET_ARG_KEYS = {
    "password",
    "app_password",
    "token",
    "private_key",
    "basic_password",
    "passphrase",
    "secret",
    "authorization",
}

_PLACEHOLDER = "•••"


def strip_secret_args(args: dict[str, Any] | None) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in (args or {}).items():
        if str(key).lower() in SECRET_ARG_KEYS:
            cleaned[key] = _PLACEHOLDER
        elif isinstance(value, dict):
            cleaned[key] = strip_secret_args(value)
        else:
            cleaned[key] = value
    return cleaned


def redact_text(text: str, secrets: Iterable[str] | None = None) -> str:
    out = text or ""
    values = sorted({str(item).strip() for item in (secrets or []) if len(str(item).strip()) >= 4}, key=len, reverse=True)
    for value in values:
        if value in out:
            out = out.replace(value, _PLACEHOLDER)
    return out


def labeled_secret_spans(text: str) -> list[str]:
    """Values written as «пароль: x» / «token: y» in free text."""
    found: list[str] = []
    pattern = re.compile(
        r"(?i)(?:пароль(?:\s+приложения)?|app\s*password|password|token|secret|ключ)\s*[:=]\s*(\S+)"
    )
    for match in pattern.finditer(text or ""):
        value = match.group(1).strip().strip(".,;\"'")
        if len(value) >= 4:
            found.append(value)
    for match in re.finditer(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", text or "", re.S):
        found.append(match.group(0))
    return found
