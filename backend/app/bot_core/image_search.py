"""Поиск по фото: Яндекс.Картинки, Google Картинки/Lens, Bing Visual Search."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import parse_qs, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

MAX_HITS_PER_ENGINE = 8
MAX_IMAGE_BYTES = 8 * 1024 * 1024
FETCH_TIMEOUT = 28

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

_SKIP_HOSTS = (
    "yandex.ru",
    "yandex.com",
    "yandex.net",
    "ya.ru",
    "yastatic.net",
    "google.com",
    "google.ru",
    "googleusercontent.com",
    "gstatic.com",
    "ggpht.com",
    "googleapis.com",
    "bing.com",
    "bing.net",
    "microsoft.com",
    "msn.com",
    "live.com",
    "w3.org",
    "schema.org",
)

_CAPTION_RE = re.compile(
    r"(?:похоже,? что на (?:фото|изображении)|best guess for this image|"
    r"pages that include matching images|страницы с этим изображением|"
    r"possible related search)[:\s]*([^\n<]{3,120})",
    re.I,
)


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _is_http_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _skip_url(url: str) -> bool:
    host = _host(url)
    if not host:
        return True
    return any(host == item or host.endswith("." + item) for item in _SKIP_HOSTS)


def unwrap_search_href(href: str, base: str = "") -> str:
    """Достаёт целевой URL из обёрток Google/Yandex."""
    href = (href or "").strip()
    if not href or href.startswith(("#", "javascript:", "data:")):
        return ""
    if href.startswith("//"):
        href = "https:" + href
    if base and href.startswith("/"):
        href = urljoin(base, href)
    parsed = urlparse(href)
    host = (parsed.hostname or "").lower()
    query = parse_qs(parsed.query)
    if "google." in host and parsed.path.startswith("/url"):
        target = (query.get("q") or query.get("url") or [""])[0]
        return target.strip() if target else ""
    if "yandex." in host and "url" in query:
        target = query.get("url", [""])[0]
        if _is_http_url(target) and not _skip_url(target):
            return target.strip()
    return href


def extract_caption(text: str) -> str:
    blob = re.sub(r"\s+", " ", text or "")
    match = _CAPTION_RE.search(blob)
    if match:
        return match.group(1).strip(" .")[:120]
    return ""


def extract_json_hits(payload: Any, found: list[dict[str, str]] | None = None) -> list[dict[str, str]]:
    """Достаёт url+title из JSON выдачи, какой бы ни была вложенность."""
    hits = found if found is not None else []
    seen = {item["url"] for item in hits}

    def walk(node: Any, depth: int = 0) -> None:
        if depth > 12 or len(hits) >= MAX_HITS_PER_ENGINE * 2:
            return
        if isinstance(node, dict):
            url = str(node.get("url") or node.get("href") or node.get("originalUrl") or "").strip()
            title = str(node.get("title") or node.get("text") or node.get("name") or "").strip()
            if _is_http_url(url) and not _skip_url(url) and url not in seen:
                seen.add(url)
                hits.append({"url": url, "title": title[:180]})
            for value in node.values():
                walk(value, depth + 1)
        elif isinstance(node, list):
            for item in node[:80]:
                walk(item, depth + 1)

    walk(payload)
    return hits[:MAX_HITS_PER_ENGINE]


def extract_html_hits(html: str, page_url: str = "") -> list[dict[str, str]]:
    soup = BeautifulSoup(html or "", "html.parser")
    hits: list[dict[str, str]] = []
    seen: set[str] = set()
    for tag in soup.find_all("a", href=True):
        url = unwrap_search_href(str(tag.get("href") or ""), page_url)
        if not _is_http_url(url) or _skip_url(url) or url in seen:
            continue
        title = " ".join(tag.get_text(" ", strip=True).split())[:180]
        seen.add(url)
        hits.append({"url": url, "title": title})
        if len(hits) >= MAX_HITS_PER_ENGINE:
            break
    return hits


def parse_engine_page(body: str, page_url: str = "") -> tuple[str, list[dict[str, str]]]:
    """Возвращает (подпись, совпадения) из HTML или JSON ответа поисковика."""
    text = body or ""
    caption = extract_caption(text)
    hits: list[dict[str, str]] = []
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            hits = extract_json_hits(json.loads(stripped))
        except json.JSONDecodeError:
            hits = []
    if not hits:
        hits = extract_html_hits(text, page_url)
    if not caption:
        for item in hits:
            if item.get("title") and len(item["title"]) >= 8:
                caption = item["title"][:120]
                break
    return caption, hits[:MAX_HITS_PER_ENGINE]


def _proxy() -> str | None:
    try:
        from config import PROXY_URL, RU_PROXY_URL

        return PROXY_URL or RU_PROXY_URL or None
    except Exception:
        return None


async def _read_body(response: aiohttp.ClientResponse) -> str:
    ctype = (response.headers.get("Content-Type") or "").lower()
    if "image/" in ctype or "octet-stream" in ctype:
        return ""
    return await response.text(errors="replace")


async def _post_form(
    session: aiohttp.ClientSession,
    url: str,
    field: str,
    image_bytes: bytes,
    filename: str,
    mime: str,
    extra_fields: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> tuple[str, str]:
    form = aiohttp.FormData()
    form.add_field(field, image_bytes, filename=filename, content_type=mime)
    for key, value in (extra_fields or {}).items():
        form.add_field(key, value)
    async with session.post(
        url,
        data=form,
        params=params,
        allow_redirects=True,
        ssl=False,
        proxy=_proxy(),
    ) as response:
        body = await _read_body(response)
        return str(response.url), body


async def _search_yandex(session: aiohttp.ClientSession, image_bytes: bytes, filename: str, mime: str) -> tuple[str, list[dict[str, str]]]:
    last_error = ""
    for host in ("https://yandex.ru/images/search", "https://yandex.com/images/search"):
        try:
            page_url, body = await _post_form(
                session,
                host,
                "upfile",
                image_bytes,
                filename,
                mime,
                params={"rpt": "imageview", "format": "json"},
            )
            caption, hits = parse_engine_page(body, page_url)
            if hits or caption:
                return caption, hits
            page_url, body = await _post_form(
                session,
                host,
                "upfile",
                image_bytes,
                filename,
                mime,
                params={"rpt": "imageview"},
            )
            caption, hits = parse_engine_page(body, page_url)
            if hits or caption:
                return caption, hits
        except Exception as exc:
            last_error = str(exc)[:160]
            logger.warning("Yandex reverse search failed via %s: %s", host, exc)
    if last_error:
        return "", [{"url": "", "title": f"Яндекс не ответил: {last_error}"}]
    return "", []


async def _search_google(session: aiohttp.ClientSession, image_bytes: bytes, filename: str, mime: str) -> tuple[str, list[dict[str, str]]]:
    last_error = ""
    attempts = (
        (
            "https://www.google.com/searchbyimage/upload",
            "encoded_image",
            {"image_content": "", "filename": filename, "sbisrc": "Google Chrome 124"},
            None,
        ),
        (
            "https://lens.google.com/v3/upload",
            "encoded_image",
            {"hl": "ru"},
            None,
        ),
    )
    for url, field, extra, params in attempts:
        try:
            page_url, body = await _post_form(session, url, field, image_bytes, filename, mime, extra, params)
            caption, hits = parse_engine_page(body, page_url)
            if hits or caption:
                return caption, hits
        except Exception as exc:
            last_error = str(exc)[:160]
            logger.warning("Google reverse search failed via %s: %s", url, exc)
    if last_error:
        return "", [{"url": "", "title": f"Google не ответил: {last_error}"}]
    return "", []


async def _search_bing(session: aiohttp.ClientSession, image_bytes: bytes, filename: str, mime: str) -> tuple[str, list[dict[str, str]]]:
    try:
        page_url, body = await _post_form(
            session,
            "https://www.bing.com/images/search?view=detailv2&iss=sbiupload&FORM=SBIHMP",
            "imageBin",
            image_bytes,
            filename,
            mime,
        )
        return parse_engine_page(body, page_url)
    except Exception as exc:
        logger.warning("Bing reverse search failed: %s", exc)
        return "", [{"url": "", "title": f"Bing не ответил: {str(exc)[:160]}"}]


def format_reverse_results(
    filename: str,
    blocks: list[tuple[str, str, list[dict[str, str]]]],
) -> str:
    lines = [
        f"Поиск по фото «{filename}» в Яндекс.Картинках, Google Картинках/Lens и Bing.",
        "Это совпадения страниц, где публиковали это или очень похожее изображение. Не считай подпись поисковика доказательством места.",
        "Дальше открой лучшие URL через browse_page и сверь ориентиры на нескольких независимых сайтах.",
        "",
    ]
    any_hit = False
    for engine, caption, hits in blocks:
        real_hits = [item for item in hits if item.get("url")]
        lines.append(f"{engine}:")
        if caption:
            lines.append(f"- подпись поисковика: {caption}")
        if not real_hits:
            note = next((item.get("title") for item in hits if item.get("title")), "совпадений нет")
            lines.append(f"- {note}")
        for item in real_hits:
            title = item.get("title") or item["url"]
            lines.append(f"- {title} – {item['url']}")
            any_hit = True
        lines.append("")
    if not any_hit:
        lines.append(
            "Поисковики не вернули страницы. Опиши ориентиры на фото и ищи их текстом, "
            "но не называй точный адрес, пока не откроешь подтверждающую страницу."
        )
    return "\n".join(lines).strip()


async def reverse_image_search(image_bytes: bytes, filename: str, mime: str = "image/jpeg") -> str:
    if not image_bytes:
        return "Файл пустой, искать нечего."
    if len(image_bytes) > MAX_IMAGE_BYTES:
        return "Фото слишком тяжёлое для поиска по картинке. Нужен файл меньше 8 МБ."
    filename = (filename or "photo.jpg").replace("\x00", "")[:80]
    mime = mime or "image/jpeg"
    timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT)
    async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
        yandex, google, bing = await _gather_engines(session, image_bytes, filename, mime)
    return format_reverse_results(
        filename,
        [
            ("Яндекс.Картинки", yandex[0], yandex[1]),
            ("Google Картинки / Lens", google[0], google[1]),
            ("Bing Visual Search", bing[0], bing[1]),
        ],
    )


async def _gather_engines(session, image_bytes, filename, mime):
    import asyncio

    raw = await asyncio.gather(
        _search_yandex(session, image_bytes, filename, mime),
        _search_google(session, image_bytes, filename, mime),
        _search_bing(session, image_bytes, filename, mime),
        return_exceptions=True,
    )
    results = []
    labels = ("Yandex", "Google", "Bing")
    for label, item in zip(labels, raw):
        if isinstance(item, Exception):
            logger.warning("%s reverse search crashed: %s", label, item)
            results.append(("", [{"url": "", "title": f"{label} не ответил: {str(item)[:160]}"}]))
        else:
            results.append(item)
    return results
