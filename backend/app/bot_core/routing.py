import re
from typing import Optional, Tuple


def _request_shape(user_text: str) -> dict:
    text = (user_text or "").strip()
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", text)
    nonempty_lines = [line for line in text.splitlines() if line.strip()]
    list_items = sum(bool(re.match(r"\s*(?:[-*•]|\d+[.)])\s+", line)) for line in nonempty_lines)
    return {
        "chars": len(text),
        "words": len(words),
        "lines": len(nonempty_lines),
        "list_items": list_items,
    }


def computer_requires_web(user_text: str) -> bool:
    """Computer browses by default, except for unambiguous private-service actions."""
    text = (user_text or "").lower()
    local_action_patterns = (
        r"\b(?:отправь|прочитай|проверь|покажи)\w*(?:\s+\w+){0,4}\s+(?:письм|почт)\w*",
        r"\b(?:ssh|vps|сервер)\b.*\b(?:команд|диск|памят|процесс|лог)\w*",
        r"\b(?:выполни|запусти)\w*\s+команд\w*",
        r"\b(?:мой|сохран[её]нн\w*)\s+(?:api|подключен)\w*",
    )
    return not any(re.search(pattern, text, re.I) for pattern in local_action_patterns)


def current_turn_has_files(messages) -> tuple[bool, bool]:
    """Files uploaded after the last assistant reply, not leftover history.

    Old photos and PDFs stay in context for the model, but they must not
    silently disable Search / Research on the next text question.
    """
    if not messages:
        return False, False
    last_assistant = -1
    for index, message in enumerate(messages):
        role = getattr(message, "role", None)
        if role is None and isinstance(message, dict):
            role = message.get("role")
        if role == "assistant":
            last_assistant = index
    has_images = False
    has_documents = False
    for message in messages[last_assistant + 1 :]:
        attachment = getattr(message, "attachment", None)
        if attachment is None and isinstance(message, dict):
            attachment = message.get("attachment")
        attachment = attachment or {}
        if not attachment:
            continue
        kind = str(attachment.get("type") or "")
        mime = str(attachment.get("mime_type") or "")
        if kind == "image" or mime.startswith("image/"):
            has_images = True
        else:
            has_documents = True
    return has_documents, has_images


def packed_has_open_documents(messages) -> bool:
    """True when the API payload already has document bodies, not just a catalog."""
    for message in messages or []:
        role = getattr(message, "role", None)
        content = getattr(message, "content", None)
        if role is None and isinstance(message, dict):
            role = message.get("role")
            content = message.get("content")
        if role != "system" or not isinstance(content, str):
            continue
        if "документ для контекста" in content and "не подмешан" not in content:
            return True
    return False


def turn_requires_web(
    user_text: str,
    model: str,
    *,
    research_mode: bool = False,
    has_documents: bool = False,
    has_images: bool = False,
) -> bool:
    """Whether this turn should leave the chat to fetch the internet.

    Search, Research and Pilot always go to the web. Auto still searches only
    when the question itself needs fresh facts. has_documents / has_images are
    accepted so callers can pass current-turn file flags without changing
    Search or Pilot.
    """
    from search_engine import query_requires_web

    if model == "kimi-k2.6" or research_mode or model == "director":
        return True
    return query_requires_web(user_text)


def openai_tool_flags(model: str, web_required: bool) -> tuple[bool, bool]:
    """(use_tools, force_web_search). Astra is a sandbox agent: never web-only."""
    if model == "gpt-6-astra":
        return True, False
    return bool(web_required), bool(web_required)


def best_route(user_text: str, reasoning_effort: Optional[str], has_deepseek: bool) -> Tuple[str, bool]:
    """Choose the best quality/cost route without spending tokens on a router call."""
    text = (user_text or "").lower()
    shape = _request_shape(user_text)
    hard_markers = (
        "архитектур", "алгоритм", "оптимиз", "напиши код", "отлад", "ошибка в код",
        "юрид", "договор", "исследован", "стратег", "противореч", "статист", "сделай ревью",
    )
    reasoning_markers = ("докажи", "математ", "выведи формул", "реши задачу", "формальное доказательство")
    soft_markers = ("проанализ", "сравни", "рассчитай", "пошагов", "подробно")

    explicit_deep = reasoning_effort not in {None, "none", "low"}
    hard_hits = sum(marker in text for marker in hard_markers)
    reasoning_hits = sum(marker in text for marker in reasoning_markers)
    soft_hits = sum(marker in text for marker in soft_markers)
    structured = shape["list_items"] >= 3 or shape["lines"] >= 8

    # A verb like "compare" is not complexity by itself. Volume, constraints,
    # structure and genuinely hard domains must justify the more expensive route.
    complex_task = bool(
        explicit_deep
        or shape["chars"] >= 900
        or hard_hits
        or reasoning_hits
        or structured
        or (soft_hits and shape["chars"] >= 360)
    )
    deep = bool(
        explicit_deep
        or reasoning_hits
        or (shape["chars"] >= 1800 and (hard_hits or structured))
    )
    if has_deepseek:
        return ("deepseek-v4-pro" if complex_task else "deepseek-v4-flash", deep)
    if complex_task:
        return ("gpt-5.6-terra", deep)
    return ("gpt-5.6-luna", False)
