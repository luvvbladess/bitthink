"""
Клиент Kimi/Moonshot для встроенного web search.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from openai import AsyncOpenAI

import re

from config import KIMI_API_KEY, KIMI_MODEL
from conversations import conversation_manager
from model_context import max_output_tokens, search_hop_messages

logger = logging.getLogger(__name__)

client = AsyncOpenAI(api_key=KIMI_API_KEY, base_url="https://api.moonshot.ai/v1") if KIMI_API_KEY else None

WEB_SEARCH_TOOL_KIMI = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the live web. Use for news, prices, dates, people, versions, "
            "and anything that may have changed. Write a specific query with an "
            "entity, the current year, and a qualifier. One information need per call. "
            "Do not retry with synonym rewrites of the same query."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query text",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results, 1-20. Default 8.",
                },
            },
            "required": ["query"],
        },
    },
}

BROWSE_PAGE_TOOL_KIMI = {
    "type": "function",
    "function": {
        "name": "browse_page",
        "description": (
            "Fetch a known URL as Markdown. Use after search when a snippet is not "
            "enough to verify a number, quote, or full article."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "http(s) URL to read",
                },
            },
            "required": ["url"],
        },
    },
}

KIMI_SEARCH_TOOLS = [WEB_SEARCH_TOOL_KIMI, BROWSE_PAGE_TOOL_KIMI]

# System prompt for the dedicated Kimi web-search mode.
# Search/fetch run through Kimi's standalone REST tools; we return structured
# passages to the model and collect sources for the UI panel.
KIMI_WEB_SEARCH_SYSTEM_PROMPT = (
    "Ты исследователь с прямым доступом к интернету. "
    "Для новостей, цен, дат, должностей, версий и всего, что могло измениться, сразу вызывай web_search. "
    "Не спрашивай разрешения и не объявляй вслух, что сейчас ищешь. "
    "Вечные определения можно без поиска. "
    "Запросы короткие и разные: один факт – один запрос, не склеивай пять тем. "
    "В запросах указывай текущий год, не прошлый. "
    "Обычный факт – 1–2 поиска; сравнение или обзор – 4–8; глубокая тема – больше, пока каждый кусок ответа на чём-то стоит. "
    "Сниппет – не доказательство спорной цифры: открой страницу через browse_page. "
    "После поиска отвечай на русском, с конкретными фактами и датами. "
    "Закрой задачу: как применить, ограничение, что проверить. Не обрывай тизером «могу подробнее». "
    "В основном тексте не ставь URL, Markdown-ссылки или маркеры цитат [1], [2]. "
    "Не делай вид, что отсутствие в первой выдаче значит «этого нет». "
    "В конце ответа обязательно приведи список использованных источников в строгом формате:\n"
    "[1] Название источника — https://example.com/page1\n"
    "[2] Название источника — https://example.com/page2\n"
    "Не выдумывай URL. Если факт не удалось проверить, напиши об этом."
)


def _parse_tool_args(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _merge_ui_sources(*batches: List[Dict[str, str]]) -> List[Dict[str, str]]:
    merged: List[Dict[str, str]] = []
    seen = set()
    for batch in batches:
        for item in batch or []:
            summary = (item.get("summary") or "").strip()
            url = summary.splitlines()[0] if summary else ""
            if not url or url in seen:
                continue
            seen.add(url)
            merged.append(item)
    return merged


async def _execute_kimi_tool(
    name: str,
    arguments: Dict[str, Any],
    *,
    user_id: int | None = None,
    research: bool = False,
) -> tuple[str, List[Dict[str, str]]]:
    """Run a Kimi tool locally via REST search/fetch. Returns (content, ui sources)."""
    from kimi_web_search import (
        format_results_for_model,
        kimi_fetch,
        kimi_search_pro,
        to_ui_sources,
    )

    if name in {"web_search", "$web_search"}:
        query = str(arguments.get("query") or arguments.get("text_query") or arguments.get("q") or "").strip()
        default_limit = 12 if research else 8
        limit = arguments.get("limit", default_limit)
        results = await kimi_search_pro(
            query,
            limit=limit,
            timeout_seconds=12,
            user_id=user_id,
        )
        return format_results_for_model(results), to_ui_sources(results)

    if name == "browse_page":
        url = str(arguments.get("url") or "").strip()
        fetched = await kimi_fetch(url, user_id=user_id)
        if fetched and fetched.get("markdown"):
            title = fetched.get("title") or url
            markdown = fetched["markdown"][:12000]
            source = {"query": title, "summary": fetched.get("url") or url}
            return f"{title}\nURL: {fetched.get('url') or url}\n\n{markdown}", [source]
        try:
            from web_scraper import fetch_url_content

            fetched_url, text = await fetch_url_content(url, use_kimi_fallback=False)
        except Exception as exc:
            return f"Не удалось открыть страницу: {exc}", []
        source = {"query": fetched_url or url, "summary": fetched_url or url}
        return f"URL: {fetched_url}\n\n{text}", [source]

    return f"Неизвестный инструмент: {name}", []


def _search_today_note() -> str:
    now = datetime.now()
    return (
        f" Сегодня {now.strftime('%d.%m.%Y')} ({now.year} год). "
        f"В поисковых запросах указывай {now.year}, не прошлый год. "
        "Не опирайся на мету или рейтинги прошедшего года, если не проверял их поиском."
    )


def _clean_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    cleaned = []
    for msg in messages:
        role = msg.get("role", "user")
        if role not in ("system", "user", "assistant"):
            continue
        content = msg.get("content") or ""
        if isinstance(content, list):
            texts = [
                str(part.get("text") or "")
                for part in content
                if isinstance(part, dict) and part.get("type") in {"text", "input_text"}
            ]
            content = "\n".join(item for item in texts if item)
        if isinstance(content, str) and content:
            cleaned.append({"role": role, "content": content.replace("\x00", "")})
    return cleaned


async def _append_tool_results(
    current_messages: List[Dict[str, Any]],
    tool_calls: Any,
    *,
    user_id: int | None = None,
    research: bool = False,
) -> List[Dict[str, str]]:
    collected: List[Dict[str, str]] = []
    for tc in tool_calls:
        parsed = _parse_tool_args(getattr(tc.function, "arguments", "") or "")
        try:
            from status_feed import announce_tool

            await announce_tool(tc.function.name, parsed)
        except Exception:
            pass
        content, ui_sources = await _execute_kimi_tool(
            tc.function.name,
            parsed,
            user_id=user_id,
            research=research,
        )
        collected.extend(ui_sources)
        current_messages.append(
            {
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tc.function.name,
                "content": content,
            }
        )
    return collected


async def get_kimi_search_brief(messages: List[Dict[str, Any]], user_text: str, user_id: int = None) -> str:
    """Ищет внешние факты и источники через Kimi REST web search."""
    global client
    if client is None and KIMI_API_KEY:
        client = AsyncOpenAI(api_key=KIMI_API_KEY, base_url="https://api.moonshot.ai/v1")
    if client is None:
        return "Kimi web search недоступен: не задан KIMI_API_KEY."

    current_messages = [
        {
            "role": "system",
            "content": (
                "Ты research desk. Ищи только внешние проверяемые факты по запросу. "
                "Сделай несколько поисковых запросов. Верни краткую выжимку: факты, даты, цифры, "
                "а в конце не менее пяти источников в формате [N] Название — URL. "
                "Не пиши финальный материал, не украшай стиль."
            ),
        },
        *_clean_messages(search_hop_messages(messages, user_text, turns=8)),
        {
            "role": "user",
            "content": (
                f"Запрос пользователя: {user_text}\n\n"
                "Найди актуальную внешнюю информацию и источники. "
                "Если внешняя информация не нужна или не найдена, скажи это явно."
            ),
        },
    ]

    last_text = ""
    total_input_tokens = 0
    total_output_tokens = 0

    def _track():
        if user_id:
            conversation_manager.track_tokens(user_id, KIMI_MODEL, total_input_tokens, total_output_tokens)

    for _ in range(4):
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=KIMI_MODEL,
                    messages=current_messages,
                    tools=KIMI_SEARCH_TOOLS,
                    extra_body={"thinking": {"type": "disabled"}},
                    max_tokens=max_output_tokens(KIMI_MODEL),
                ),
                timeout=60,
            )
        except asyncio.TimeoutError:
            logger.error("Kimi search brief call timed out after 60s")
            _track()
            return last_text or "Поиск через Kimi не завершился за отведённое время."
        except Exception as e:
            logger.error(f"Kimi search brief call failed: {e}", exc_info=True)
            _track()
            return last_text or f"Ошибка поиска через Kimi: {str(e)[:200]}"
        usage = getattr(response, "usage", None)
        if usage:
            total_input_tokens += getattr(usage, "prompt_tokens", 0) or 0
            total_output_tokens += getattr(usage, "completion_tokens", 0) or 0

        choice = response.choices[0]
        message = choice.message
        if message.content:
            last_text = message.content

        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            _track()
            return message.content or last_text or "Kimi не вернул результат поиска."

        current_messages.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in tool_calls
            ],
        })
        await _append_tool_results(current_messages, tool_calls, user_id=user_id)

    _track()
    return last_text or "Kimi web search не завершился за лимит шагов."


def _extract_urls(text: str) -> List[str]:
    """Извлекает все http/https URL из текста."""
    return re.findall(r"https?://[^\s\)\]\>\"\']+", text)


def _parse_cited_sources(text: str) -> List[Dict[str, str]]:
    """
    Парсит источники вида [1] Название — URL из конца ответа Kimi.
    Возвращает список {query: title, summary: url}.
    """
    results = []
    # Ищем блок с нумерованными источниками в конце текста.
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^\[(\d+)\]\s*(.+)$", line)
        if not m:
            continue
        body = m.group(2).strip()
        # Разделитель: длинное тире/дефис/минус между названием и URL
        parts = re.split(r"\s+[-–—]\s+", body)
        if len(parts) >= 2:
            title = parts[0].strip()
            url = parts[-1].strip()
        else:
            # Если разделителя нет, пытаемся найти URL в строке
            urls = _extract_urls(body)
            title = re.sub(r"https?://\S+", "", body).strip()
            url = urls[0] if urls else ""
        if url:
            results.append({"query": title or "Источник", "summary": url})
    return results


def _build_search_results_from_text(text: str) -> List[Dict[str, str]]:
    """
    Собирает источники для UI из текста ответа Kimi.
    Сначала пытаемся распарсить цитаты [N], затем фоллбэк на прямые URL.
    """
    cited = _parse_cited_sources(text)
    if cited:
        return cited
    urls = _extract_urls(text)
    seen = set()
    results = []
    for url in urls:
        url = url.rstrip(".,;:!?)\">")
        if url in seen:
            continue
        seen.add(url)
        results.append({"query": "Источник", "summary": url})
    return results


_EMPTY_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+•‣∙·]|\d+[.)])\s*$")
# ASCII labels plus punycode (xn--p1ai and friends). Numeric-only TLDs are
# excluded so "(2024.12)" is not treated as a citation.
_DNS_HOST = r"(?:www\.)?(?:[a-z0-9-]+\.)+(?:xn--[a-z0-9-]+|[a-z]{2,24})"
_PAREN_DOMAIN_RE = re.compile(rf"\s*\({_DNS_HOST}(?:/[^\s)]*)?\)", re.I)
_BARE_PUNYCODE_RE = re.compile(r"\(?xn--[a-z0-9-]+(?:\.xn--[a-z0-9-]+)+\)?", re.I)
# Leftover wiki/path fragments after a URL was stripped, e.g. "перевозки.էական".
_FOREIGN_SCRIPT_TAIL_RE = re.compile(
    r"(?<=[A-Za-zА-Яа-яЁё])\.["
    r"\u0530-\u058F"
    r"\u10A0-\u10FF"
    r"\u0600-\u06FF"
    r"\u0590-\u05FF"
    r"\u0900-\u097F"
    r"\u4E00-\u9FFF"
    r"\u3040-\u30FF"
    r"]+"
)


def drop_empty_list_items(text: str) -> str:
    """Remove leftover bullets after citations/URLs were stripped from a list."""
    if not text:
        return text
    kept = [line for line in text.splitlines() if not _EMPTY_LIST_ITEM_RE.match(line)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


_SOURCE_HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*{1,2}|_{1,2})?(?:источники|sources)\s*:?\s*(?:\*{1,2}|_{1,2})?\s*$",
    re.I,
)
_SOURCE_ITEM_RE = re.compile(
    r"^\s*(?:[-*+•‣∙·]|\d+[.)])?\s*(?:\*{1,2}|_{1,2})?источник(?:и)?\b",
    re.I,
)
_SOURCE_LIST_RE = re.compile(
    r"^\s*(?:[-*+•‣∙·]|\d+[.)])\s*(?:\[[^\]]+\]\(https?://|<?https?://|\[\d+\])",
    re.I,
)


def _is_source_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    return bool(
        _SOURCE_HEADING_RE.match(stripped)
        or _SOURCE_ITEM_RE.match(stripped)
        or _SOURCE_LIST_RE.match(stripped)
        or re.match(r"^\[\d+\]\s+", stripped)
    )


def _cut_trailing_source_block(lines: List[str]) -> List[str]:
    start = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if _SOURCE_HEADING_RE.match(stripped) or _SOURCE_ITEM_RE.match(stripped) or _SOURCE_LIST_RE.match(stripped):
            rest = lines[index:]
            if all(_is_source_line(item) for item in rest):
                start = index
                break
    if start is None:
        return lines
    trimmed = lines[:start]
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    return trimmed


def strip_source_links(text: str) -> str:
    """Убирает ссылки и inline-цитаты; источники остаются только в панели UI."""
    if not text:
        return text
    cleaned_lines: List[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if re.match(r"^\s*\[\d+\]\s+.*(?:https?://\S+|\([\w.-]+\.[a-z]{2,}\))\s*$", line, re.I):
            continue
        if _SOURCE_HEADING_RE.match(stripped) or _SOURCE_ITEM_RE.match(stripped):
            continue
        cleaned_lines.append(line)
    cleaned_lines = _cut_trailing_source_block(cleaned_lines)
    cleaned = "\n".join(cleaned_lines)
    cleaned = re.sub(r"\[([^\]]+)\]\(https?://[^)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"(?<!\()https?://[^\s<>)\]]+", "", cleaned)
    cleaned = re.sub(r"\s*\[\d+\]", "", cleaned)
    # Hosted search models sometimes render citation annotations as a bare
    # domain in parentheses, e.g. "(casio.com)" or a punycode ".рф" host.
    # The clickable source lives in the UI panel, so this duplicate is removed.
    cleaned = _PAREN_DOMAIN_RE.sub("", cleaned)
    cleaned = _BARE_PUNYCODE_RE.sub("", cleaned)
    cleaned = _FOREIGN_SCRIPT_TAIL_RE.sub("", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return drop_empty_list_items(cleaned)


def extract_domain_sources(text: str) -> List[Dict[str, str]]:
    """Last-resort source recovery when an API returns domain citations only."""
    seen = set()
    results: List[Dict[str, str]] = []
    patterns = [
        r"https?://[^\s<>)\]]+",
        rf"\(({_DNS_HOST})(?:/[^\s)]*)?\)",
        r"\b(xn--[a-z0-9-]+(?:\.xn--[a-z0-9-]+)+)\b",
    ]
    for pattern_index, pattern in enumerate(patterns):
        for match in re.finditer(pattern, text or "", flags=re.I):
            raw = match.group(0) if pattern_index == 0 else match.group(1)
            url = raw.rstrip(".,;:!?)\">") if pattern_index == 0 else f"https://{raw}"
            domain = re.sub(r"^https?://(?:www\.)?", "", url, flags=re.I).split("/")[0]
            if not domain or domain in seen:
                continue
            seen.add(domain)
            results.append({"query": domain, "summary": url})
    return results


def kimi_result_is_grounded(answer: str, sources: List[Dict[str, str]], minimum_sources: int = 2) -> bool:
    """Строгая проверка перед тем, как доверить пользователю результат Kimi."""
    return bool(
        answer
        and not answer.lstrip().startswith("❌")
        and len(answer.strip()) >= 120
        and len(sources) >= minimum_sources
    )


async def get_kimi_chat_response(
    messages: List[Dict[str, Any]], user_id: int = None, on_reasoning_delta: Optional[Any] = None,
    research: bool = False,
) -> Tuple[str, List[Dict[str, Any]], str, List[Dict[str, str]]]:
    """
    Режим "Поиск в интернете" через Kimi K2.6.

    Модель вызывает обычные function-tools `web_search` / `browse_page`; мы исполняем
    их через Kimi REST (`/v1/tools/search_pro`, `/v1/tools/fetch`) и собираем
    источники из структурированного ответа, с фоллбэком на цитаты в тексте.

    Возвращает (текст_ответа, файлы, текст_размышлений, результаты_поиска).
    """
    global client
    if client is None and KIMI_API_KEY:
        client = AsyncOpenAI(api_key=KIMI_API_KEY, base_url="https://api.moonshot.ai/v1")
    if client is None:
        return "❌ Пожалуйста, укажите KIMI_API_KEY в config.py для использования этой модели.", [], "", []

    current_messages = _clean_messages(messages)
    # Ensure the system prompt for native web search/citations is present.
    search_prompt = KIMI_WEB_SEARCH_SYSTEM_PROMPT + _search_today_note()
    if research:
        search_prompt += (
            "\nЭто углублённое исследование: разбей вопрос на подвопросы, выполни несколько отдельных "
            "поисковых проходов, проверь противоречия и постарайся использовать 14–24 содержательных источника."
        )
    if not current_messages or current_messages[0].get("role") != "system":
        current_messages.insert(0, {"role": "system", "content": search_prompt})
    else:
        current_messages[0]["content"] = search_prompt + "\n\n" + current_messages[0].get("content", "")

    generated_files: List[Dict[str, Any]] = []
    collected_sources: List[Dict[str, str]] = []
    last_text = ""
    total_input_tokens = 0
    total_output_tokens = 0

    def _track():
        if user_id:
            conversation_manager.track_tokens(user_id, KIMI_MODEL, total_input_tokens, total_output_tokens)

    def _final_sources(text: str) -> List[Dict[str, str]]:
        return _merge_ui_sources(collected_sources, _build_search_results_from_text(text or ""))

    for _ in range(10):
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=KIMI_MODEL,
                    messages=current_messages,
                    tools=KIMI_SEARCH_TOOLS,
                    extra_body={"thinking": {"type": "disabled"}},
                    max_tokens=max_output_tokens(KIMI_MODEL),
                ),
                timeout=420,
            )
        except asyncio.TimeoutError:
            logger.error("Kimi chat API call timed out after 420s")
            _track()
            return "❌ Модель Kimi не ответила за 420 секунд (таймаут)", [], "", _final_sources(last_text)
        except Exception as e:
            logger.error(f"Kimi chat API call failed: {e}", exc_info=True)
            _track()
            return f"❌ Ошибка API Kimi: {str(e)}", [], "", _final_sources(last_text)

        usage = getattr(response, "usage", None)
        if usage:
            total_input_tokens += getattr(usage, "prompt_tokens", 0) or 0
            total_output_tokens += getattr(usage, "completion_tokens", 0) or 0

        choice = response.choices[0]
        message = choice.message
        if message.content:
            last_text = message.content

        tool_calls = getattr(message, "tool_calls", None) or []
        assistant_msg: Dict[str, Any] = {"role": "assistant", "content": message.content or ""}
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": tc.type,
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ]
        current_messages.append(assistant_msg)

        if not tool_calls:
            _track()
            search_results = _final_sources(message.content or "")
            answer = strip_source_links(message.content or "")
            return answer or "Нет ответа от модели", generated_files, "", search_results

        collected_sources.extend(
            await _append_tool_results(
                current_messages, tool_calls, user_id=user_id, research=research
            )
        )

    logger.warning("Kimi chat: exhausted max loops")
    _track()
    return last_text or "Нет ответа от модели", generated_files, "", _final_sources(last_text)
