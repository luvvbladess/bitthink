"""Поисковый слой: Kimi native web search с резервом OpenAI web search."""

import re
import logging
import asyncio
from typing import List, Dict, Any
from urllib.parse import urlparse
# Импорт DDGS перенесен внутрь функций для подавления предупреждений во время выполнения
from openai import AsyncOpenAI
from web_scraper import fetch_url_content
from config import PROXY_URL, OPENAI_API_KEY

logger = logging.getLogger(__name__)


def query_requires_web(query: str) -> bool:
    """Deterministic guard for requests that must not be answered from memory.

    This intentionally catches explicit search language and volatile commercial
    or time-sensitive facts. Dedicated Search/Research modes are forced by the
    caller regardless of this classifier.
    """
    text = (query or "").lower().strip()
    if not text:
        return False
    patterns = (
        r"\bзагугл\w*\b",
        r"\b(?:поищ|найд)\w*\s+(?:в\s+)?(?:интернет|сет|веб)\w*\b",
        r"\b(?:web|internet)\s*search\b",
        r"\b(?:сегодня|сейчас|вчера|актуальн\w*|последн\w*|свеж\w*)\b",
        r"\b(?:на|в)\s+(?:данный|текущий)\s+момент\b",
        r"\b(?:at\s+the\s+moment|currently|right\s+now|as\s+of\s+now)\b",
        r"\b(?:рейтинг\w*|популярн\w*|бестселлер\w*|топ[-\s]?\d*)\b",
        r"\bсам(?:ый|ая|ое|ые|ым|ыми|ых|ому|ую)\s+(?:крут\w*|сильн\w*|мощн\w*)\b",
        r"\b(?:мете|мета|тир[-\s]?лист|tier[\s-]?list|патч.?нот\w*|patch\s*notes)\b",
        r"\b(?:цен\w*|стоимост\w*|курс\w*|котиров\w*|погод\w*)\b",
        r"https?://",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _extract_keywords(query: str) -> List[str]:
    """Извлекает значимые слова из запроса для проверки релевантности."""
    return [w.lower() for w in re.findall(r"[a-zA-Z0-9а-яА-ЯёЁ]{4,}", query)]


def _clean_snippet(snippet: str) -> str:
    """Убирает служебные маркеры цитирования OpenAI из сниппета."""
    if not snippet:
        return snippet
    # Удаляем маркеры вида citeturn0search0
    snippet = re.sub(r"[^]*", "", snippet)
    # Удаляем [wordlim: 200] и подобные служебные теги
    snippet = re.sub(r"\[[a-z]+:\s*[^\]]*\]", "", snippet)
    # Удаляем OpenAI-служебные префиксы результатов
    snippet = re.sub(r"(Crawled|Published|Content type|Source|Total chunks):\s*[^;]*;?\s*", "", snippet, flags=re.IGNORECASE)
    return snippet.strip()


def _sources_look_useful(sources: List[Dict[str, str]], query: str) -> bool:
    """Проверяем, не вернул ли поисковик мусор/заглушки."""
    if len(sources) < 2:
        return False
    keywords = _extract_keywords(query)
    if not keywords:
        return True
    relevant = 0
    for src in sources:
        text = f"{src.get('title', '')} {src.get('url', '')} {src.get('snippet', '')}".lower()
        if any(kw in text for kw in keywords):
            relevant += 1
    return relevant / len(sources) >= 0.3


async def _search_ddg(query: str, max_results: int) -> List[Dict[str, str]]:
    """Поиск через DuckDuckGo."""
    loop = asyncio.get_event_loop()

    def _perform(q: str, m: int, region: str | None):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            from duckduckgo_search import DDGS
            with DDGS(proxy=PROXY_URL if PROXY_URL else None) as ddgs:
                return list(ddgs.text(q, max_results=m, region=region))

    results: List[Dict] = []
    try:
        results = await loop.run_in_executor(None, _perform, query, max_results, None)
        if not results:
            results = await loop.run_in_executor(None, _perform, query, max_results, "ru-ru")
    except Exception as e:
        logger.warning(f"DuckDuckGo search failed: {e}")

    sources = []
    for res in results:
        href = res.get("href", "")
        if not href:
            continue
        sources.append({"title": res.get("title", "Без заголовка"), "url": href, "snippet": _clean_snippet(res.get("body", ""))})
    return sources


async def _search_openai_sources(query: str, max_results: int) -> List[Dict[str, str]]:
    """Фоллбэк: поиск источников через OpenAI Responses API (web_search tool)."""
    if not OPENAI_API_KEY:
        return []
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            resp = await asyncio.wait_for(
                client.responses.create(
                    model="gpt-5.6-luna",
                    input=f"Выполни веб-поиск по запросу и используй актуальные источники: {query}",
                    tools=[{"type": "web_search"}],
                    tool_choice="required",
                    include=["web_search_call.results", "web_search_call.action.sources"],
                ),
                timeout=45,
            )
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                await asyncio.sleep(0.5)
                continue
            break

        sources: List[Dict[str, str]] = []
        seen = set()

        def add_source(raw: Any) -> None:
            if isinstance(raw, dict):
                title = raw.get("title") or "Без заголовка"
                url = raw.get("url") or ""
                snippet = raw.get("content") or raw.get("snippet") or ""
            else:
                title = getattr(raw, "title", None) or "Без заголовка"
                url = getattr(raw, "url", None) or ""
                snippet = getattr(raw, "content", None) or getattr(raw, "snippet", None) or ""
            if not url or url in seen:
                return
            seen.add(url)
            sources.append({"title": title, "url": url, "snippet": _clean_snippet(snippet)})

        for item in resp.output:
            if getattr(item, "type", None) == "web_search_call":
                for result in (getattr(item, "results", None) or []):
                    add_source(result)
                action = getattr(item, "action", None)
                for source in (getattr(action, "sources", None) or []):
                    add_source(source)
            if getattr(item, "type", None) == "message":
                for content in (getattr(item, "content", None) or []):
                    for annotation in (getattr(content, "annotations", None) or []):
                        if getattr(annotation, "type", None) == "url_citation":
                            add_source(annotation)

        if sources:
            return sources[:max_results]
        if attempt == 0:
            await asyncio.sleep(0.5)

    if last_error:
        logger.warning(f"OpenAI web search fallback failed: {last_error}")
    else:
        logger.warning("OpenAI web search fallback returned no sources after retry")
    return []


async def _search_kimi_sources(query: str, max_results: int) -> List[Dict[str, str]]:
    """Получает источники через нативный $web_search Kimi, без DDG-прокси."""
    try:
        from kimi_client import _build_search_results_from_text, get_kimi_search_brief

        brief = await get_kimi_search_brief([], query)
        if brief.startswith(("Ошибка поиска", "Kimi web search недоступен", "Поиск через Kimi")):
            return []
        items = _build_search_results_from_text(brief)
        sources: List[Dict[str, str]] = []
        for item in items[:max_results]:
            url = (item.get("summary") or "").splitlines()[0]
            if not url.startswith(("http://", "https://")):
                continue
            sources.append({"title": item.get("query") or "Источник", "url": url, "snippet": ""})
        return sources
    except Exception as exc:
        logger.warning(f"Kimi web search failed: {exc}")
        return []


async def search_web(query: str, max_results: int = 14) -> List[Dict[str, str]]:
    """
    Выполняет поиск и возвращает структурированные источники.

    Приоритет: нативный Kimi $web_search. Если Kimi не вернул как минимум два
    пригодных источника, автоматически используем OpenAI web search.
    """
    sources = await _search_kimi_sources(query, max_results)
    if _sources_look_useful(sources, query):
        return sources

    logger.info(f"Kimi results poor for '{query[:60]}', trying OpenAI web search fallback")
    openai_sources = await _search_openai_sources(query, max_results)
    if openai_sources and _sources_look_useful(openai_sources, query):
        return openai_sources
    # Если и OpenAI не дал релевантных источников, лучше ничего не показывать,
    # чем показывать мусорные/заглушечные результаты.
    return []


async def get_web_search_sources(query: str, max_results: int = 14) -> List[Dict[str, str]]:
    """Публичная обёртка для получения источников веб-поиска."""
    return await search_web(query, max_results=max_results)


async def build_grounded_web_context(query: str, max_results: int = 14, pages_to_read: int = 6) -> tuple[str, List[Dict[str, str]]]:
    """Perplexity-style shared retrieval stage used before every normal answer.

    Kimi gathers the candidate sources, then we read several top pages and pass
    numbered evidence to the selected model. OpenAI search is the automatic fallback.
    """
    from status_feed import push_status

    await push_status("search", f"Ищу: {query[:90]}")
    sources = await search_web(query, max_results=max_results)
    if not sources:
        await push_status("search", "Свежих источников не найдено — отвечаю по контексту")
        return "", []

    await push_status("search", f"Нашёл {len(sources)} источников")
    selected = sources[:pages_to_read]
    for source in selected:
        host = urlparse(source.get("url", "")).netloc.replace("www.", "")
        await push_status("browse", f"Читаю {host or source.get('title', 'источник')}")

    fetched = await asyncio.gather(
        *(fetch_url_content(source.get("url", "")) for source in selected),
        return_exceptions=True,
    )
    content_by_url: Dict[str, str] = {}
    for source, result in zip(selected, fetched):
        if isinstance(result, Exception):
            continue
        url, content = result
        if content:
            content_by_url[url] = content[:6000]

    blocks = []
    for index, source in enumerate(sources, 1):
        url = source.get("url", "")
        body = content_by_url.get(url) or source.get("snippet", "")
        blocks.append(f"[{index}] {source.get('title', 'Источник')}\nURL: {url}\n{body}")

    await push_status("think", "Сопоставляю факты из источников")
    ui_sources = [
        {
            "query": source.get("title", "Источник"),
            "summary": f"{source.get('url', '')}\n{source.get('snippet', '')}".strip(),
        }
        for source in sources
    ]
    return "\n\n".join(blocks), ui_sources


async def smart_web_search(query: str, max_results: int = 14) -> str:
    """
    Выполняет поиск в DuckDuckGo, получает сниппеты и докачивает контент по топовым ссылкам.
    
    Args:
        query: Поисковой запрос
        max_results: Количество результатов для анализа
        
    Returns:
        Сводная информация из сети в формате текста.
    """
    try:
        sources = await search_web(query, max_results=max_results)
        
        if not sources:
            return "По вашему запросу ничего не найдено в сети."
            
        # 2. Формируем краткий обзор
        search_report = []
        
        urls_to_scrape = []
        for i, src in enumerate(sources):
            title = src["title"]
            href = src["url"]
            body = src["snippet"]
            
            search_report.append(f"{i+1}. **{title}**\nURL: {href}\nСниппет: {body}\n")
            
            # Добавляем лучшие ссылки в очередь на полный скрапинг (топ-8)
            if i < 8:
                urls_to_scrape.append(href)
        
        # 3. Докачиваем контент (параллельно)
        if urls_to_scrape:
            tasks = [fetch_url_content(url) for url in urls_to_scrape]
            scrape_results = await asyncio.gather(*tasks)
            
            for url, content in scrape_results:
                # Берем до 4000 символов для глубокого контекста
                clean_content = content[:4000]
                search_report.append(f"\n--- [ПОЛНЫЙ КОНТЕНТ С САЙТА: {url}] ---\n{clean_content}\n--- [КОНЕЦ КОНТЕНТА] ---\n")
        
        return "\n".join(search_report)
        
    except Exception as e:
        logger.error(f"Error in smart_web_search: {e}")
        return f"Произошла ошибка при поиске в сети: {str(e)}"

async def check_if_search_needed(user_query: str, model: str = "gpt-5.6-luna") -> bool:
    """
    Использует ИИ, чтобы определить, нужен ли поиск в сети для ответа на этот вопрос.
    """
    from openai_client import get_simple_response
    
    prompt = f"""Проанализируй запрос. Твоя задача — решить, нужен ли поиск в интернете.
Ответь ТОЛЬКО "SEARCH", если запрос касается:
- Новостей за последние дни/недели
- Игровых патчей, обновлений софта, дат релизов
- Текущих курсов валют, погоды, времени
- Любых фактов, которые могут измениться (кто выиграл вчера матч и т.д.)

Если это простое общение, приветствие или вопрос по общей базе знаний (как сварить борщ) — ответь "NO".

Запрос: "{user_query}"
"""
    try:
        response, _ = await get_simple_response(prompt, model=model)
        logger.info(f"Search decision for '{user_query[:30]}': {response.strip()}")
        return "SEARCH" in response.upper()
    except Exception as e:
        logger.error(f"Error in check_if_search_needed: {e}")
        return False
