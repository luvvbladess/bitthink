"""Suggest an existing mode when the current one cannot do what was asked.

The check is lexical and conservative: a supported action stays in the current
mode. Locked modes (not on the user's plan) are never offered.
"""

from __future__ import annotations

import json
import re
from typing import Iterable, Optional

MODE_SWITCH_QUERY = "__mode_switch__"

_PILOT_CAPABLE = {"director", "gpt-6-astra"}
_STUDIO_CAPABLE = {"studio", "director", "gpt-6-astra"}
_NO_WEB = {"studio", "docgen"}

_PILOT_ACTION = re.compile(
    r"(?i)(?:"
    r"\b(?:проверь(?:те)?|посмотри(?:те)?)\b[^.\n]{0,40}\b(?:почт\w*|письм\w*|gmail|входящ\w*)"
    r"|"
    r"\b(?:отправ(?:ь|ьте|ить))\b[^.\n]{0,40}\b(?:письм\w*|email|e-mail|gmail)"
    r"|"
    r"\b(?:зайди(?:те)?|зайти|открой(?:те)?)\b[^.\n]{0,48}\b(?:сайт\w*|почт\w*|сервер\w*|vps|ssh|кабинет\w*)"
    r"|"
    r"\b(?:по|через)\s+ssh\b"
    r"|"
    r"\bssh\b[^.\n]{0,40}\b(?:команд\w*|сервер\w*|подключ\w*)"
    r"|"
    r"\b(?:выполни(?:те)?|запусти(?:те)?)\b[^.\n]{0,30}\bкоманд\w*"
    r")"
)

_DOCGEN = re.compile(
    r"(?i)(?:"
    r"(?:соберите|собери(?:те)?|сделай(?:те)?|подготовь(?:те)?|сгенерируй(?:те)?|создай(?:те)?)"
    r"[^.\n]{0,80}"
    r"(?:документ\w*|docx|\.docx|word|ворд)"
    r"[^.\n]{0,60}"
    r"(?:шаблон\w*|архив\w*|баз\w+\s+знан\w*)"
    r"|"
    r"(?:шаблон\w*|баз\w+\s+знан\w*|архив\w*)"
    r"[^.\n]{0,80}"
    r"(?:документ\w*|docx|\.docx|word|ворд)"
    r"|"
    r"отдельн\w+\s+документ\w+[^.\n]{0,40}шаблон"
    r"|"
    r"полн\w+\s+документ[^.\n]{0,40}прикрепл"
    r")"
)

_STUDIO_NOUN = re.compile(
    r"(?i)\b(презентац\w*|слайд\w*|питч\w*|powerpoint|pptx|инфографик\w*|лендинг\w*|дашборд\w*|dashboard)\b"
)
_CREATE = re.compile(
    r"(?i)\b(сделай(?:те)?|собери(?:те)?|собрать|сверстай(?:те)?|создай(?:те)?|создать|подготовь(?:те)?|нарисуй(?:те)?|сгенерируй(?:те)?)\b"
)
_ANALYZE = re.compile(
    r"(?i)\b(проанализ\w*|разбер\w*|разобра\w*|суммир\w*|перескаж\w*|что внутри|о чём|найди ошиб\w*|сравни)\b"
)

_SEARCH = re.compile(
    r"(?i)(?:"
    r"\b(?:поищи(?:те)?|поискай(?:те)?|погугли(?:те)?)\b"
    r"|"
    r"\bнайди(?:те)?\b[^.\n]{0,24}\b(?:в интернете|в сети|новост\w*)"
    r"|"
    r"\bчто (?:сегодня|сейчас)\b[^.\n]{0,40}\b(?:в мире|в новост\w*|произош\w*)"
    r"|"
    r"\bактуальн\w+\s+(?:новост\w*|данн\w+|событи\w*)"
    r")"
)
_RESEARCH = re.compile(
    r"(?i)(?:"
    r"глубок\w+\s+(?:исследован\w+|разбор\w+)"
    r"|"
    r"исследуй(?:те)?\s+источник"
    r"|"
    r"разбор\w+\s+источник"
    r")"
)

_SPECS = {
    "studio": {
        "model": "studio",
        "label": "Студия",
        "reason": "Слайды, лендинг и инфографика собирает Студия.",
        "accept": "Перейти в Студию",
        "done": "Студия включена",
    },
    "docgen": {
        "model": "docgen",
        "label": "Документы",
        "reason": "Большой документ по шаблонам и базе собирает режим «Документы».",
        "accept": "Перейти в Документы",
        "done": "Документы включены",
    },
    "director": {
        "model": "director",
        "label": "Пилот",
        "reason": "Зайти на сайт, в почту или на сервер может Пилот.",
        "accept": "Перейти в Пилот",
        "done": "Пилот включён",
    },
    "kimi-k2.6": {
        "model": "kimi-k2.6",
        "label": "Поиск",
        "reason": "Свежий ответ с источниками даёт режим «Поиск».",
        "accept": "Перейти в Поиск",
        "done": "Поиск включён",
    },
    "gpt-6-sol": {
        "model": "gpt-6-sol",
        "label": "Исследование",
        "reason": "Глубокий разбор источников делает режим «Исследование».",
        "accept": "Перейти в Исследование",
        "done": "Исследование включено",
    },
}


def _allowed(target: str, allowed: Optional[Iterable[str]]) -> bool:
    if allowed is None:
        return True
    return target in set(allowed)


def _wants_studio(text: str) -> bool:
    if not _STUDIO_NOUN.search(text):
        return False
    if _ANALYZE.search(text) and not _CREATE.search(text):
        return False
    return bool(_CREATE.search(text))


def suggest_mode_switch(
    model: str,
    user_text: str,
    *,
    allowed: Optional[Iterable[str]] = None,
) -> Optional[dict]:
    """Return the public suggestion dict, or None when the current mode can proceed."""
    text = (user_text or "").strip()
    if len(text) < 8:
        return None
    try:
        from clarify import is_clarify_reply

        if is_clarify_reply(text):
            return None
    except Exception:
        pass

    target: Optional[str] = None
    if _PILOT_ACTION.search(text) and model not in _PILOT_CAPABLE:
        target = "director"
    elif _DOCGEN.search(text) and model != "docgen":
        target = "docgen"
    elif _wants_studio(text) and model not in _STUDIO_CAPABLE:
        target = "studio"
    elif model in _NO_WEB and _RESEARCH.search(text):
        target = "gpt-6-sol" if _allowed("gpt-6-sol", allowed) else "kimi-k2.6"
    elif model in _NO_WEB and _SEARCH.search(text):
        target = "kimi-k2.6"

    if not target or target == model or not _allowed(target, allowed):
        return None
    spec = dict(_SPECS[target])
    spec["text"] = spec["reason"]
    return spec


def pack_mode_switch(suggestion: dict) -> list[dict]:
    payload = {
        "model": suggestion["model"],
        "label": suggestion["label"],
        "reason": suggestion["reason"],
        "accept": suggestion["accept"],
        "done": suggestion["done"],
    }
    return [{"query": MODE_SWITCH_QUERY, "summary": json.dumps(payload, ensure_ascii=False)}]
