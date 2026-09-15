"""Durable user preferences, accumulated across chats and injected into context."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

MEMORY_MAX_CHARS = 1400
MEMORY_MIN_SNIPPET = 24
DEBOUNCE_SECONDS = 25
IDLE_REFRESH_SECONDS = 2 * 60 * 60
MAX_TURNS = 8
TURN_CHARS = 360
MAX_BULLETS = 10

EXTRACTOR_INSTRUCTIONS = (
    "Ты ведёшь краткую карточку предпочтений человека, не конспект чата. "
    "Записывай только устойчивое, что он сам сказал о себе или о том, как ему отвечать: "
    "язык, тон, формат (таблица, Word, коротко), обращение, профессия, повторяющиеся темы. "
    "Не копируй формулировки задач. Не пиши «пользователь просит», «сделай», «проанализируй», "
    "имена файлов, суммы, номера пунктов, названия компаний и текущий проект. "
    "Не записывай пароли, ключи, адреса, телефоны, здоровье и разовые факты. "
    "Советы ассистента и результаты поиска не клади. "
    "Если нового устойчивого нет, ответь ровно: БЕЗ_ИЗМЕНЕНИЙ. "
    "Иначе верни полный актуальный список: маркированные пункты на русском, максимум 10, "
    "без заголовка, без предисловия, каждый пункт как факт о человеке."
)

WRAPPER = (
    "Устойчивые предпочтения человека из прошлых разговоров. "
    "Это не текущая задача и не факты прошлого чата. "
    "Подстрой тон, язык и формат, только если это помогает этому ответу. "
    "Не тащи прошлые проекты, суммы, файлы и разовые поручения. "
    "Не цитируй этот блок и не говори, что что-то запомнил, "
    "пока человек сам не спросит, что ты о нём знаешь.\n\n"
    "{notes}"
)

_SECRET = re.compile(
    r"(password|пароль|api[_-]?key|secret|token|sk-[a-z0-9]|bearer\s+\S+|-----BEGIN)",
    re.I,
)
_NO_CHANGE = re.compile(r"(?i)^\s*(без[_\s-]*изменений|нет нового|unchanged|пусто)\s*[.!]?\s*$")
_PREF_SIGNAL = re.compile(
    r"(?i)("
    r"\bвсегда\b|\bникогда\b|предпочит|запомни|забудь|"
    r"пиши как|отвечай коротк|без воды|на ты\b|на вы\b|"
    r"мне удобнее|мне лучше|я (?:работаю|юрист|инженер|бухгалтер|врач|дизайнер)|"
    r"в таблиц|формате?\s*(?:word|excel|pdf)|по-русски|на русском|"
    r"обращайся|не используй канцеляр"
    r")"
)
_DURABLE = re.compile(
    r"(?i)("
    r"\bвсегда\b|\bникогда\b|предпочит|стиль|формат|кратко|коротк|подробно|"
    r"без воды|на ты\b|на вы\b|по-русски|на русском|таблиц|"
    r"\bword\b|\bexcel\b|\bpdf\b|обращайся|пиши как|"
    r"я (?:работаю|юрист|инженер|бухгалтер)|професси|тон ответов|"
    r"макет|не стандартн|оригинальн|интересу"
    r")"
)
_TRANSCRIPT = re.compile(r"(?i)^(пользователь|ассистент|запрос|тема|результат поиска)\s*:")
_JUNK = re.compile(
    r"(?i)^("
    r"проанализируй|посмотри|сделай|приложен|хотим |хочет |"
    r"хочу |да,?\s*сделай|не могу отправить|прикрепл|"
    r"запросил |проверь |перепроверь|сколько примерно|"
    r"ты инженер|ты юрист|ты бухгалтер|не указан"
    r")"
)
_ONE_OFF = re.compile(
    r"(?i)("
    r"в этом чате|на данный момент|прикреплённ|приложенн|"
    r"этап\s*\d|ооо\s*[«\"]|н·м|руб\.|тред\.|"
    r"штабное расписание|инфографик"
    r")"
)

CompleteFn = Callable[[str, str], Awaitable[str]]


def _strip_bullet(line: str) -> str:
    return (line or "").strip().lstrip("•*-–— ").strip()


def parse_bullets(text: str) -> list[str]:
    items: list[str] = []
    for line in (text or "").splitlines():
        stripped = _strip_bullet(line)
        if stripped:
            items.append(stripped)
    return items


def is_durable_bullet(text: str) -> bool:
    line = _strip_bullet(text)
    if len(line) < 10:
        return False
    if _SECRET.search(line) or _TRANSCRIPT.search(line):
        return False
    if _DURABLE.search(line):
        return True
    if _JUNK.search(line) or _ONE_OFF.search(line) or line.endswith("?"):
        return False
    if re.match(r"(?i)^я\b", line) and len(line) < 90:
        return True
    return False


def _normalize_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower())


def _near_duplicate(left: str, right: str) -> bool:
    a = _normalize_key(left)
    b = _normalize_key(right)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    words_a = {w for w in re.findall(r"[a-zа-яё0-9]{4,}", a) }
    words_b = {w for w in re.findall(r"[a-zа-яё0-9]{4,}", b) }
    if not words_a or not words_b:
        return False
    overlap = len(words_a & words_b)
    return overlap >= 3 and overlap / min(len(words_a), len(words_b)) >= 0.7


def format_notes(items: list[str]) -> str:
    lines: list[str] = []
    for item in items:
        stripped = _strip_bullet(item)
        if not stripped:
            continue
        if len(stripped) > 140:
            stripped = stripped[:137].rstrip() + "..."
        lines.append(f"- {stripped}")
        if len(lines) >= MAX_BULLETS:
            break
    return "\n".join(lines)[:MEMORY_MAX_CHARS].rstrip()


def scrub_notes(text: str) -> str:
    return format_notes([item for item in parse_bullets(text) if is_durable_bullet(item)])


def merge_notes(current: str, extracted: str) -> str:
    if is_no_change(extracted):
        return scrub_notes(current)
    incoming = [item for item in parse_bullets(extracted) if is_durable_bullet(item)]
    if not incoming:
        return scrub_notes(current)
    merged: list[str] = []
    for item in parse_bullets(current) + incoming:
        if not is_durable_bullet(item):
            continue
        if any(_near_duplicate(item, kept) for kept in merged):
            continue
        merged.append(_strip_bullet(item))
    return format_notes(merged)


def sanitize_notes(text: str) -> str:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:\w+)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    if is_no_change(raw):
        return ""
    return scrub_notes(raw)


def is_no_change(text: str) -> bool:
    return bool(_NO_CHANGE.match((text or "").strip()))


def snippet_hash(snippet: str) -> str:
    return hashlib.sha256((snippet or "").encode("utf-8")).hexdigest()[:16]


def has_preference_signal(snippet: str) -> bool:
    return bool(_PREF_SIGNAL.search(snippet or ""))


def should_refresh(memory: dict[str, Any], snippet: str, now: int | None = None) -> bool:
    if not memory.get("enabled", True):
        return False
    if len((snippet or "").strip()) < MEMORY_MIN_SNIPPET:
        return False
    digest = snippet_hash(snippet)
    if digest and digest == (memory.get("last_hash") or ""):
        return False
    now = int(now or time.time())
    updated = int(memory.get("updated_at") or 0)
    age = now - updated if updated else 10**9
    if has_preference_signal(snippet):
        return age >= DEBOUNCE_SECONDS
    return age >= IDLE_REFRESH_SECONDS


def memory_system_message(memory: dict[str, Any]) -> dict[str, str] | None:
    notes = scrub_notes(memory.get("notes") or "")
    if not memory.get("enabled", True) or not notes:
        return None
    return {"role": "system", "content": WRAPPER.format(notes=notes)}


def build_extractor_prompt(current_notes: str, snippet: str) -> str:
    current = scrub_notes(current_notes) or "пусто"
    return (
        "Текущая карточка предпочтений:\n"
        f"{current}\n\n"
        "Новые реплики человека (не копируй их в память, вытащи только устойчивое):\n"
        f"{snippet.strip()}\n"
    )


def _manager():
    import conversations

    return conversations.conversation_manager


def collect_snippet(user_id: int) -> str:
    conv = _manager().get_active_conversation(user_id)
    if not conv:
        return ""
    lines: list[str] = []
    for message in conv.messages:
        if message.role != "user":
            continue
        if getattr(message, "attachment", None):
            continue
        text = " ".join((message.content or "").split())
        if len(text) < 12:
            continue
        if re.fullmatch(r"(?i)(да|нет|ок|окей|сделай|продолжи|ещё|еще)\.?", text):
            continue
        lines.append(text[:TURN_CHARS])
    return "\n".join(f"- {line}" for line in lines[-MAX_TURNS:])


async def _complete_nano(instructions: str, prompt: str, user_id: int = 0) -> str:
    from openai_client import _get_reasoning_config, _resolve_api_model, client

    response = await client.responses.create(
        model=_resolve_api_model("gpt-5-nano"),
        input=[{"role": "user", "content": prompt}],
        instructions=instructions,
        max_output_tokens=400,
        truncation="auto",
        reasoning=_get_reasoning_config("gpt-5-nano", user_effort="low"),
    )
    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) != "message":
            continue
        for part in getattr(item, "content", []) or []:
            if getattr(part, "type", None) == "output_text":
                chunks.append(getattr(part, "text", "") or "")
    usage = getattr(response, "usage", None)
    if usage and user_id:
        try:
            _manager().track_tokens(
                user_id,
                "gpt-5-nano",
                getattr(usage, "input_tokens", 0) or 0,
                getattr(usage, "output_tokens", 0) or 0,
            )
        except Exception:
            pass
    return "".join(chunks).strip()


async def refresh_user_memory(user_id: int, complete: CompleteFn | None = None) -> None:
    memory = await asyncio.to_thread(_manager().get_user_memory, user_id)
    if not memory.get("enabled", True):
        return
    current = memory.get("notes") or ""
    cleaned = scrub_notes(current)
    snippet = await asyncio.to_thread(collect_snippet, user_id)
    if not should_refresh(memory, snippet):
        if cleaned != current.strip():
            await asyncio.to_thread(_manager().save_user_memory, user_id, notes=cleaned)
        return
    complete = complete or (lambda instructions, prompt: _complete_nano(instructions, prompt, user_id))
    try:
        raw = await complete(EXTRACTOR_INSTRUCTIONS, build_extractor_prompt(current, snippet))
    except Exception as exc:
        logger.info("User memory refresh skipped: %s", exc)
        if cleaned != current.strip():
            await asyncio.to_thread(_manager().save_user_memory, user_id, notes=cleaned)
        return
    notes = merge_notes(current, raw)
    await asyncio.to_thread(
        _manager().save_user_memory,
        user_id,
        notes=notes,
        last_hash=snippet_hash(snippet),
        updated_at=int(time.time()),
    )


def schedule_refresh(user_id: int) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_guarded_refresh(user_id), name=f"user-memory-{user_id}")


async def _guarded_refresh(user_id: int) -> None:
    try:
        await refresh_user_memory(user_id)
    except Exception as exc:
        logger.info("User memory task failed: %s", exc)
