"""Per-turn context that must not sit in the cached system prefix."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

_RU_MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


def current_date_note() -> str:
    now = datetime.now()
    return (
        f"Сегодня {now.day} {_RU_MONTHS[now.month - 1]} {now.year} года "
        f"({now.strftime('%d.%m.%Y')}). Это реальное «сегодня». "
        f"В поиске и датах используй {now.year}, не прошлый год."
    )


def last_user_text(messages: List[Dict[str, Any]] | None) -> str:
    for message in reversed(messages or []):
        if (message.get("role") if isinstance(message, dict) else None) != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text") or part.get("content") or ""
                if text:
                    parts.append(str(text))
            return " ".join(parts)
    return ""


def _already_has_preloaded_skills(messages: List[Dict[str, Any]] | None) -> bool:
    marker = "Скилы уже подобраны под этот ход"
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str) and marker in content:
            return True
    return False


def messages_have_images(messages: List[Dict[str, Any]] | None) -> bool:
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") in {"image_url", "input_image"}:
                    return True
        attachment = message.get("attachment") or {}
        if attachment.get("type") == "image" or str(attachment.get("mime_type") or "").startswith("image/"):
            return True
    return False


def with_runtime_context(
    messages: List[Dict[str, Any]],
    *,
    use_skills: bool = False,
    skill_limit: int = 2,
    user_id: int | None = None,
    sandbox: bool = False,
) -> List[Dict[str, Any]]:
    """Date and matched skills as extra system items. First system stays cacheable."""
    extras: List[str] = [current_date_note()]
    if use_skills and not _already_has_preloaded_skills(messages):
        try:
            from computer_skills.loader import preload_skills_block

            block = preload_skills_block(
                last_user_text(messages),
                has_images=messages_have_images(messages),
                limit=max(1, min(int(skill_limit), 4)),
                user_id=user_id,
                sandbox=sandbox,
            )
            if block:
                extras.append(block)
        except Exception:
            pass
    out = [dict(item) for item in messages]
    insert_at = 1 if out and out[0].get("role") == "system" else 0
    for offset, text in enumerate(extras):
        out.insert(insert_at + offset, {"role": "system", "content": text})
    return out
