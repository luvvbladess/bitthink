"""Standalone Kimi Web Search / Fetch REST client.

Replaces the legacy builtin `$web_search` flow (deprecated 2026-10-20).
Billed per successful call that returns data: search $0.002, search_pro $0.003,
fetch $0.002. Empty or failed calls are free.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import aiohttp

from config import KIMI_API_KEY, KIMI_MODEL

logger = logging.getLogger(__name__)

KIMI_TOOLS_BASE = "https://api.moonshot.ai/v1"
SEARCH_PATH = "/tools/search"
SEARCH_PRO_PATH = "/tools/search_pro"
FETCH_PATH = "/tools/fetch"

MAX_LIMIT = 20
DEFAULT_SEARCH_TIMEOUT = 20
DEFAULT_PRO_TIMEOUT = 30
DEFAULT_FETCH_TIMEOUT = 25


def _clamp_limit(limit: int | None, default: int = 5) -> int:
    try:
        value = int(limit if limit is not None else default)
    except (TypeError, ValueError):
        value = default
    return max(1, min(MAX_LIMIT, value))


def _track_calls(user_id: int | None, count: int = 1) -> None:
    if not user_id or count <= 0:
        return
    try:
        from conversations import conversation_manager

        conversation_manager.track_calls(user_id, KIMI_MODEL, count)
    except Exception:
        logger.exception("Failed to track Kimi search calls for user %s", user_id)


async def _post_json(path: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    if not KIMI_API_KEY:
        logger.warning("Kimi tools %s skipped: KIMI_API_KEY is not set", path)
        return {}
    url = f"{KIMI_TOOLS_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {KIMI_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        timeout_cfg = aiohttp.ClientTimeout(total=max(5, int(timeout)))
        async with aiohttp.ClientSession(timeout=timeout_cfg) as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status != 200:
                    body = await response.text()
                    logger.warning(
                        "Kimi tools %s HTTP %s: %s",
                        path,
                        response.status,
                        (body or "")[:300],
                    )
                    return {}
                data = await response.json(content_type=None)
                return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("Kimi tools %s failed: %s", path, exc)
        return {}


def normalize_search_results(raw: Any) -> List[Dict[str, Any]]:
    """Turn a REST payload into a list of result dicts."""
    items = raw.get("search_results") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    results: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        chunks = []
        for chunk in item.get("chunks") or []:
            if not isinstance(chunk, dict):
                continue
            text = str(chunk.get("text") or "").strip()
            if not text:
                continue
            score = chunk.get("score")
            try:
                score_value = float(score) if score is not None else 0.0
            except (TypeError, ValueError):
                score_value = 0.0
            chunks.append({"text": text, "score": score_value})
        results.append(
            {
                "title": str(item.get("title") or "Источник").strip() or "Источник",
                "url": url,
                "snippet": str(item.get("snippet") or "").strip(),
                "text": str(item.get("text") or "").strip(),
                "site_name": str(item.get("site_name") or "").strip(),
                "date": str(item.get("date") or "").strip(),
                "authority": str(item.get("authority") or "").strip(),
                "chunks": chunks,
            }
        )
    return results


def to_engine_sources(results: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Map REST results to search_engine source cards."""
    sources: List[Dict[str, str]] = []
    for item in results:
        snippet = item.get("snippet") or ""
        if not snippet and item.get("chunks"):
            snippet = str(item["chunks"][0].get("text") or "")[:400]
        sources.append(
            {
                "title": item.get("title") or "Источник",
                "url": item.get("url") or "",
                "snippet": snippet,
            }
        )
    return sources


def to_ui_sources(results: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Map REST results to the chat UI search panel."""
    cards: List[Dict[str, str]] = []
    seen = set()
    for item in results:
        url = item.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        snippet = item.get("snippet") or ""
        cards.append(
            {
                "query": item.get("title") or "Источник",
                "summary": f"{url}\n{snippet}".strip(),
            }
        )
    return cards


def format_results_for_model(results: List[Dict[str, Any]]) -> str:
    """Compact evidence block for a tool result message."""
    if not results:
        return "По запросу ничего не найдено."
    blocks = []
    for index, item in enumerate(results, 1):
        chunks = item.get("chunks") or []
        if chunks:
            body = "\n".join(str(chunk.get("text") or "") for chunk in chunks[:6] if chunk.get("text"))
        else:
            body = item.get("text") or item.get("snippet") or ""
        meta = []
        if item.get("site_name"):
            meta.append(item["site_name"])
        if item.get("date"):
            meta.append(item["date"])
        if item.get("authority"):
            meta.append(f"authority={item['authority']}")
        header = f"[{index}] {item.get('title') or 'Источник'}"
        if meta:
            header += f" ({', '.join(meta)})"
        blocks.append(f"{header}\nURL: {item.get('url')}\n{body}".strip())
    return "\n\n".join(blocks)


def evidence_from_results(results: List[Dict[str, Any]], max_chars: int = 6000) -> Dict[str, str]:
    """URL -> best available page text for grounded context."""
    content: Dict[str, str] = {}
    for item in results:
        url = item.get("url") or ""
        if not url:
            continue
        chunks = item.get("chunks") or []
        if chunks:
            body = "\n".join(str(chunk.get("text") or "") for chunk in chunks if chunk.get("text"))
        else:
            body = item.get("text") or item.get("snippet") or ""
        body = body.strip()
        if body:
            content[url] = body[:max_chars]
    return content


async def kimi_search(
    query: str,
    *,
    limit: int = 5,
    include_content: bool = False,
    timeout_seconds: int = DEFAULT_SEARCH_TIMEOUT,
    user_id: int | None = None,
) -> List[Dict[str, Any]]:
    text = (query or "").strip()
    if not text:
        return []
    payload: Dict[str, Any] = {
        "text_query": text,
        "limit": _clamp_limit(limit),
        "timeout_seconds": max(1, min(60, int(timeout_seconds))),
        "include_content": bool(include_content),
    }
    data = await _post_json(SEARCH_PATH, payload, timeout=timeout_seconds + 8)
    results = normalize_search_results(data)
    if results:
        _track_calls(user_id)
    return results


async def kimi_search_pro(
    query: str,
    *,
    limit: int = 5,
    sites: Optional[List[str]] = None,
    time_window: Optional[Dict[str, str]] = None,
    timeout_seconds: int = DEFAULT_PRO_TIMEOUT,
    user_id: int | None = None,
) -> List[Dict[str, Any]]:
    text = (query or "").strip()
    if not text:
        return []
    payload: Dict[str, Any] = {
        "text_query": text,
        "limit": _clamp_limit(limit, default=8),
        "timeout_seconds": max(1, min(60, int(timeout_seconds))),
    }
    cleaned_sites = [str(site).strip() for site in (sites or []) if str(site).strip()][:5]
    if cleaned_sites:
        payload["sites"] = cleaned_sites
    if isinstance(time_window, dict) and (time_window.get("start") or time_window.get("end")):
        payload["time_window"] = {
            key: str(time_window[key])
            for key in ("start", "end")
            if time_window.get(key)
        }
    data = await _post_json(SEARCH_PRO_PATH, payload, timeout=timeout_seconds + 8)
    results = normalize_search_results(data)
    if results:
        _track_calls(user_id)
    return results


async def kimi_fetch(url: str, *, user_id: int | None = None) -> Optional[Dict[str, str]]:
    target = (url or "").strip()
    if not target.startswith(("http://", "https://")):
        return None
    data = await _post_json(FETCH_PATH, {"url": target}, timeout=DEFAULT_FETCH_TIMEOUT)
    markdown = str((data or {}).get("markdown") or "").strip()
    if not markdown:
        return None
    _track_calls(user_id)
    return {
        "url": str(data.get("url") or target),
        "title": str(data.get("title") or "").strip(),
        "markdown": markdown,
    }
