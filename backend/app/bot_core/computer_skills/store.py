"""Per-user custom skills. Builtin playbooks stay on disk; these live in the DB."""

from __future__ import annotations

import re
from typing import Any

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
MAX_SKILLS = 20
MAX_BODY = 4000
MAX_DESC = 180
MAX_TITLE = 80
MAX_TRIGGERS = 400
_SECRET = re.compile(
    r"(password|пароль|api[_-]?key|secret|token|sk-[a-z0-9]|bearer\s+\S+|-----BEGIN)",
    re.I,
)


def normalize_name(name: str) -> str:
    return (name or "").strip().lower().replace("-", "_").replace(" ", "_")


def parse_triggers(raw: str) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for chunk in re.split(r"[,;\n]+", raw or ""):
        needle = " ".join(chunk.lower().split())
        if len(needle) < 3 or needle in seen:
            continue
        seen.add(needle)
        parts.append(needle)
        if len(parts) >= 12:
            break
    text = ", ".join(parts)
    return text[:MAX_TRIGGERS]


def _clean_text(value: str, limit: int) -> str:
    text = (value or "").strip()
    if _SECRET.search(text):
        raise ValueError("В скил нельзя класть пароли, ключи и токены.")
    return text[:limit]


def reserved_names() -> set[str]:
    from computer_skills.loader import builtin_names

    return set(builtin_names()) | {
        "save_skill",
        "delete_skill",
        "list_skills",
        "load_skill",
        "builtin",
        "custom",
    }


def validate_payload(
    *,
    name: str,
    description: str,
    body: str,
    title: str = "",
    triggers: str = "",
    allow_reserved: bool = False,
) -> dict[str, str]:
    slug = normalize_name(name)
    if not NAME_RE.match(slug):
        raise ValueError("Имя скила – латиница, цифры и _, с буквы, до 32 знаков. Например: bitship_tone")
    if not allow_reserved and slug in reserved_names():
        raise ValueError(f"Имя «{slug}» занято общим скилом. Выберите другое.")
    desc = _clean_text(description, MAX_DESC)
    if not desc:
        raise ValueError("Нужно короткое описание: когда применять скил.")
    text = _clean_text(body, MAX_BODY)
    if len(text) < 12:
        raise ValueError("В правилах скила слишком мало текста.")
    heading = _clean_text(title or slug, MAX_TITLE)
    return {
        "name": slug,
        "title": heading,
        "description": desc,
        "body": text,
        "triggers": parse_triggers(triggers),
    }


def public_skill(row: dict[str, Any], *, origin: str) -> dict[str, Any]:
    return {
        "name": row.get("name") or "",
        "title": row.get("title") or row.get("name") or "",
        "description": row.get("description") or "",
        "body": row.get("body") or "",
        "triggers": row.get("triggers") or "",
        "enabled": bool(row.get("enabled", True)),
        "origin": origin,
        "scope": "chat" if origin == "custom" else "sandbox",
    }
