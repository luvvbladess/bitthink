"""Structured clarifying questions for Computer mode (Perplexity-style chips)."""

from __future__ import annotations

import json
import re
from typing import Any

CLARIFY_QUERY = "__clarify__"
MAX_QUESTIONS = 3
MIN_OPTIONS = 2
MAX_OPTIONS = 6
MAX_PROMPT_CHARS = 160
MAX_OPTION_CHARS = 80

_REPLY_PREFIX = "Уточнения по задаче:"
_SKIP_PREFIX = "Уточнения пропущены"


def is_clarify_reply(text: str) -> bool:
    stripped = (text or "").strip()
    return stripped.startswith(_REPLY_PREFIX) or stripped.startswith(_SKIP_PREFIX)


def _clean_line(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = text.replace("—", "–").replace("<", "").replace(">", "")
    return text[:limit]


def normalize_questions(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    questions: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        prompt = _clean_line(item.get("prompt") or item.get("question") or "", MAX_PROMPT_CHARS)
        if len(prompt) < 8:
            continue
        options: list[str] = []
        seen: set[str] = set()
        for option in item.get("options") or []:
            label = _clean_line(option, MAX_OPTION_CHARS)
            key = label.lower()
            if len(label) < 1 or key in seen:
                continue
            seen.add(key)
            options.append(label)
            if len(options) >= MAX_OPTIONS:
                break
        if len(options) < MIN_OPTIONS:
            continue
        questions.append({"prompt": prompt, "options": options})
        if len(questions) >= MAX_QUESTIONS:
            break
    return questions


def pack_search(questions: list[dict[str, Any]]) -> list[dict[str, str]]:
    payload = json.dumps({"questions": questions}, ensure_ascii=False)
    return [{"query": CLARIFY_QUERY, "summary": payload}]


def unpack_search(search: list[dict[str, str]] | None) -> list[dict[str, Any]] | None:
    if not search:
        return None
    for item in search:
        if not isinstance(item, dict) or item.get("query") != CLARIFY_QUERY:
            continue
        try:
            data = json.loads(item.get("summary") or "")
        except json.JSONDecodeError:
            return None
        questions = normalize_questions(data.get("questions") if isinstance(data, dict) else None)
        return questions or None
    return None
