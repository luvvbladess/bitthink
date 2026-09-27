"""Deterministic personal-skill commands from any chat mode.

Modes that never call tools (Studio, Documents, Pilot's planner) still have to
save a skill when the person asks. The reply states what actually happened:
the model is not asked to invent «сохранил».
"""

from __future__ import annotations

import re
from contextvars import ContextVar
from dataclasses import dataclass

_STATE: ContextVar[str] = ContextVar("skill_save_state", default="")

_POLITE = re.compile(r"^(?:пожалуйста|please|pls)[,!\s]+", re.I)
_SAVE = re.compile(
    r"(?is)(?P<pre>.*?)(?P<cmd>"
    r"запомни(?:те)?(?:\s+это)?\s+как\s+(?:мой\s+)?скил"
    r"|добавь(?:те)?\s+(?:мой\s+)?скил"
    r"|сохрани(?:те)?\s+(?:это\s+)?(?:как\s+)?(?:мой\s+)?скил"
    r")\b(?P<rest>.*)$"
)
_NAME = re.compile(
    r"^\s*[:\-—–]?\s*(?P<name>[A-Za-z][A-Za-z0-9_\-]{1,31})\b\s*[:\-—–.]?\s*(?P<body>.*)$",
    re.S,
)
_DELETE = re.compile(
    r"(?is)^(?:пожалуйста[,!\s]+)?(?:удали(?:те)?|убери(?:те)?)\s+(?:мой\s+)?скил\s+"
    r"([A-Za-z][A-Za-z0-9_\-]{1,31})\s*[.!]?\s*$"
)
_SHOW = re.compile(
    r"(?is)^(?:пожалуйста[,!\s]+)?покажи(?:те)?\s+(?:мой\s+)?скил\s+"
    r"([A-Za-z][A-Za-z0-9_\-]{1,31})\s*[.!]?\s*$"
)
_LIST = re.compile(
    r"(?is)^(?:пожалуйста[,!\s]+)?(?:покажи(?:те)?(?:\s+мне)?|какие(?:\s+у\s+меня)?|список)\s+"
    r"(?:мои\s+)?скил\w*\s*\??\s*$"
)
_CLAIM = re.compile(r"(скил\w*.{0,48}сохран\w*|сохран\w*.{0,48}скил\w*)", re.I)
_NOT_SAVED = re.compile(r"не\s+сохран", re.I)


@dataclass
class SkillTurn:
    reply: str | None = None
    messages: list | None = None


def begin_skill_turn() -> None:
    _STATE.set("")


def mark_skill_saved() -> None:
    _STATE.set("saved")


def skill_was_saved() -> bool:
    return _STATE.get() == "saved"


def guard_unsaved_claim(text: str) -> str:
    """Drop a claim that a skill was saved when this turn did not save one."""
    if skill_was_saved() or not text or not _CLAIM.search(text):
        return text

    def _replace(match: re.Match[str]) -> str:
        start = max(0, match.start() - 16)
        window = text[start:match.end() + 16]
        if _NOT_SAVED.search(window):
            return match.group(0)
        return "Скил не сохранён"

    return _CLAIM.sub(_replace, text)


def _mixed(pre: str) -> bool:
    core = _POLITE.sub("", pre or "").strip(" \t\n\r,.;:!-—–")
    if not core:
        return False
    if len(core) <= 2 and core.lower() in {"а", "и", "ну"}:
        return False
    return True


def _fail(reason: str) -> str:
    return f"Скил не сохранён. {reason}"


def _save(user_id: int, rest: str) -> str:
    from conversations import conversation_manager

    parsed = _NAME.match(rest or "")
    if not parsed:
        return _fail("Нужно имя латиницей и правила. Например: запомни как скил office_tone: служебные письма, на вы, без смайлов.")
    name = parsed.group("name")
    body = " ".join((parsed.group("body") or "").split())
    if len(body) < 12:
        return _fail("В правилах слишком мало текста. Напишите, когда применять скил и как отвечать.")
    description = body[:180]
    try:
        row = conversation_manager.save_user_skill(
            int(user_id),
            name=name,
            description=description,
            body=body,
        )
    except ValueError as exc:
        return _fail(str(exc))
    except Exception:
        return _fail("Не удалось записать скил. Добавьте его в Настройках.")
    mark_skill_saved()
    saved = (row or {}).get("name") or name
    return (
        f"Скил «{saved}» сохранён только для вас. "
        "Он действует в других ваших чатах и виден в Настройках."
    )


def _delete(user_id: int, name: str) -> str:
    from conversations import conversation_manager

    try:
        ok = conversation_manager.delete_user_skill(int(user_id), name)
    except ValueError as exc:
        return str(exc)
    if not ok:
        return "Такого своего скила нет. Общие удалить нельзя."
    return f"Скил «{name.strip().lower().replace('-', '_').replace(' ', '_')}» удалён."


def _list(user_id: int) -> str:
    from computer_skills.loader import turn_is_shared
    from conversations import conversation_manager

    rows = conversation_manager.list_user_skills(int(user_id), enabled_only=False)
    if not rows:
        return "Своих скилов пока нет. Добавьте фразой «запомни как скил имя: правила» или в Настройках."
    names = ", ".join(str(row.get("name") or "") for row in rows if row.get("name"))
    if turn_is_shared(user_id):
        return f"Ваши скилы: {names}. Правила в Настройках – в общий чат их целиком не копирую."
    lines = [f"Ваши скилы: {names}."]
    for row in rows:
        desc = str(row.get("description") or "").strip()
        if desc:
            lines.append(f"- {row.get('name')}: {desc}")
    lines.append("Правила целиком – в Настройках.")
    return "\n".join(lines)


def _show(user_id: int, name: str) -> str:
    from computer_skills.loader import turn_is_shared
    from conversations import conversation_manager

    row = conversation_manager.get_user_skill(int(user_id), name)
    if not row:
        return "Такого своего скила нет. Общие плейбуки в чат целиком не копируются."
    if turn_is_shared(user_id):
        return (
            f"Скил «{row.get('name')}» – {row.get('description') or 'личный'}. "
            "Правила в Настройках. В общий чат их целиком не копирую."
        )
    return f"# {row.get('title') or row.get('name')}\n{row.get('description') or ''}\n\n{row.get('body') or ''}"


def _inject(messages: list, note: str) -> list:
    out = [dict(item) for item in messages]
    insert_at = 1 if out and out[0].get("role") == "system" else 0
    out.insert(
        insert_at,
        {
            "role": "system",
            "content": (
                "Факт по личному скилу этого человека, уже записанный в базу. "
                "Не противоречь ему и не пиши, что скил сохранён, если ниже сказано обратное.\n"
                + note
            ),
        },
    )
    return out


def apply_skill_turn(user_id: int | None, text: str, messages: list | None = None) -> SkillTurn | None:
    """Handle an explicit skill phrase. None means this turn is ordinary chat."""
    if not user_id:
        return None
    raw = text or ""
    save = _SAVE.search(raw)
    if save:
        reply = _save(int(user_id), save.group("rest") or "")
        if _mixed(save.group("pre") or ""):
            return SkillTurn(messages=_inject(list(messages or []), reply))
        return SkillTurn(reply=reply)
    delete = _DELETE.match(raw.strip())
    if delete:
        return SkillTurn(reply=_delete(int(user_id), delete.group(1)))
    show = _SHOW.match(raw.strip())
    if show:
        return SkillTurn(reply=_show(int(user_id), show.group(1)))
    if _LIST.match(raw.strip()):
        return SkillTurn(reply=_list(int(user_id)))
    return None
