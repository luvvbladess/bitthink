"""
Модуль для извлечения содержимого веб-страниц из ссылок в сообщениях.
Находит все URL в тексте, скачивает контент и подставляет его в запрос.
"""

import re
import json
import time
import logging
import asyncio
from urllib.parse import parse_qs, unquote, urlparse, urljoin
from typing import List, Optional, Tuple

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
reader_audit = logging.getLogger('uvicorn.error.marketplace_reader')

# Регулярка для поиска URL в тексте
URL_PATTERN = re.compile(
    r'(https?://[^\s<>\"\'\)\]\,]+)',
    re.IGNORECASE
)

# Лимиты
MAX_URLS = 5               # Макс. ссылок для обработки в одном сообщении
MAX_CONTENT_PER_URL = 15000  # Макс. символов текста с одной страницы
FETCH_TIMEOUT = 15          # Таймаут на скачивание (секунды)

# User-Agent для обхода простых блокировок
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}

# Прокси через российский сервер (для обхода гео-блокировок)
from config import RU_PROXY_URL


# Ссылка на файл Google Диска: /file/d/ID/..., ?id=ID, /open?id=ID
GDRIVE_PATTERN = re.compile(
    r'drive\.google\.com/(?:file/d/([a-zA-Z0-9_-]+)|(?:open|uc)\?[^\s]*\bid=([a-zA-Z0-9_-]+))',
    re.IGNORECASE
)
GDRIVE_MAX_SIZE = 200 * 1024 * 1024  # 200MB защитный лимит на скачивание


def extract_gdrive_file_id(text: str) -> Optional[str]:
    """Находит первую ссылку на файл Google Диска в тексте и возвращает его file_id."""
    match = GDRIVE_PATTERN.search(text)
    if not match:
        return None
    return next((g for g in match.groups() if g), None)


async def _read_gdrive_response(resp: aiohttp.ClientResponse, file_id: str) -> Tuple[Optional[bytes], Optional[str], str]:
    if resp.status != 200:
        return None, None, f"[Ошибка загрузки с Google Диска: HTTP {resp.status}]"

    content_length = resp.headers.get("Content-Length")
    if content_length and int(content_length) > GDRIVE_MAX_SIZE:
        return None, None, f"[Ошибка: файл больше {GDRIVE_MAX_SIZE // (1024 * 1024)}MB]"

    filename = file_id
    cd = resp.headers.get("Content-Disposition", "")
    name_match = re.search(r'filename\*?="?(?:UTF-8\'\')?([^";]+)"?', cd)
    if name_match:
        filename = name_match.group(1)

    # Читаем потоково и обрываем сразу при превышении лимита — Content-Length может
    # отсутствовать (chunked-ответ), поэтому resp.read() целиком небезопасен для памяти.
    chunks = []
    total = 0
    async for chunk in resp.content.iter_chunked(1024 * 1024):
        total += len(chunk)
        if total > GDRIVE_MAX_SIZE:
            return None, None, f"[Ошибка: файл больше {GDRIVE_MAX_SIZE // (1024 * 1024)}MB]"
        chunks.append(chunk)

    return b"".join(chunks), filename, ""


async def download_gdrive_file(file_id: str) -> Tuple[Optional[bytes], Optional[str], str]:
    """
    Скачивает файл с Google Диска по file_id (ссылка должна быть открыта на доступ "Все, у кого есть ссылка").
    Для больших файлов Google Диск отдаёт HTML-страницу с предупреждением — обходим через токен confirm.
    Возвращает (bytes, filename, сообщение_об_ошибке). bytes=None при ошибке.
    """
    base_url = f"https://drive.google.com/uc?export=download&id={file_id}"
    timeout = aiohttp.ClientTimeout(total=120)
    try:
        async with aiohttp.ClientSession(timeout=timeout, headers=HEADERS) as session:
            async with session.get(base_url, allow_redirects=True, ssl=False) as resp:
                content_type = resp.headers.get("Content-Type", "")
                if "text/html" in content_type:
                    html_text = await resp.text(errors="replace")
                    confirm_match = re.search(r'confirm=([0-9A-Za-z_-]+)', html_text)
                    if not confirm_match:
                        return None, None, "[Ошибка: не удалось скачать файл с Google Диска. Проверьте, что доступ открыт по ссылке.]"
                    confirm_url = f"https://drive.google.com/uc?export=download&confirm={confirm_match.group(1)}&id={file_id}"
                    async with session.get(confirm_url, allow_redirects=True, ssl=False) as resp2:
                        return await _read_gdrive_response(resp2, file_id)
                return await _read_gdrive_response(resp, file_id)
    except asyncio.TimeoutError:
        return None, None, "[Ошибка: превышено время ожидания загрузки с Google Диска]"
    except Exception as e:
        logger.error(f"Google Drive download error: {e}")
        return None, None, f"[Ошибка загрузки с Google Диска: {str(e)[:100]}]"


def find_urls(text: str) -> List[str]:
    """Находит все URL в тексте."""
    urls = URL_PATTERN.findall(text)
    # Убираем дубликаты, сохраняя порядок
    seen = set()
    unique = []
    for url in urls:
        # Очищаем URL от возможных лишних символов на конце
        url = url.rstrip('.,;:!?')
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique[:MAX_URLS]


def _product_metadata(soup: BeautifulSoup) -> str:
    """Keep product facts embedded in JSON-LD before removing script tags."""
    products = []

    def visit(value):
        if isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            kind = value.get("@type", [])
            kinds = [kind] if isinstance(kind, str) else kind
            if isinstance(kinds, list) and any(str(k).rsplit("/", 1)[-1] == "Product" for k in kinds):
                facts = {k: value[k] for k in (
                    "name", "description", "sku", "brand", "offers", "aggregateRating", "review",
                ) if k in value}
                if facts:
                    products.append(json.dumps(facts, ensure_ascii=False))
            for child in value.values():
                if isinstance(child, (dict, list)):
                    visit(child)

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            visit(json.loads(script.string or script.get_text()))
        except (ValueError, TypeError, RecursionError):
            continue
    if not products:
        return ""
    return "Данные товара из страницы (JSON-LD):\n" + "\n".join(products)[:MAX_CONTENT_PER_URL]


def _clean_html(html: str, page_url: str = '') -> str:
    """Извлекает чистый текст из HTML, удаляя скрипты, стили и навигацию."""
    soup = BeautifulSoup(html, "html.parser")
    product_facts = _product_metadata(soup)
    cards = {}
    for link in soup.select('a[href]'):
        target = urljoin(page_url, link.get('href', ''))
        parsed = urlparse(target)
        if not is_ru_marketplace(target) or parsed.scheme != 'https':
            continue
        if not re.match(r'^/(product0?/|card/|product--[^/]+/|catalog/\d+/detail\.aspx)', parsed.path):
            continue
        cards.setdefault(target, link.get_text(' ',strip=True)[:180] or 'Карточка товара')
        if len(cards) >= 24:
            break
    candidate_links = ('Ссылки на отдельные карточки из страницы (ещё не проверены):\n'+ '\n'.join(f'{label} — {target}' for target,label in cards.items())+'\n\n') if cards else ''
    
    # Удаляем ненужные теги, НО ОСТАВЛЯЕМ header и aside, так как там часто лежат виджеты курсов
    for tag in soup(["script", "style", "nav", "footer", 
                     "form", "iframe", "noscript", "svg",
                     "button", "input", "select", "textarea",
                     "menu", "menuitem"]):
        tag.decompose()
    
    # Удаляем скрытые элементы и навигационные блоки
    for tag in soup.find_all(class_=re.compile(
        r"(nav|menu|breadcrumb|sidebar|cookie|banner|popup|modal|share|social|widget|advert|promo|footer|header)", 
        re.I
    )):
        tag.decompose()
    
    for tag in soup.find_all(id=re.compile(
        r"(nav|menu|breadcrumb|sidebar|cookie|banner|popup|modal|share|social|widget|advert|promo|footer|header)", 
        re.I
    )):
        tag.decompose()
    
    # Расширенный поиск основного контента — пробуем множество селекторов
    candidates = [
        soup.find("article"),
        soup.find("main"),
        soup.find(role="main"),
        soup.find(class_=re.compile(r"(article|post[-_]?content|entry[-_]?content|page[-_]?content|main[-_]?content|news[-_]?content|single[-_]?content|detail)", re.I)),
        soup.find(id=re.compile(r"(article|content|main|post|entry|page[-_]?body|news)", re.I)),
        soup.find(class_=re.compile(r"(content|text|body|wrapper|container)", re.I)),
    ]
    
    # Берём первого непустого кандидата с достаточным количеством текста
    main_content = None
    for candidate in candidates:
        if candidate:
            candidate_text = candidate.get_text(strip=True)
            if len(candidate_text) > 200:
                main_content = candidate
                break
    
    # Если ни один селектор не дал хорошего результата — ищем самый большой div
    if not main_content:
        all_divs = soup.find_all(["div", "section"])
        best_div = None
        best_len = 0
        for div in all_divs:
            t = div.get_text(strip=True)
            if len(t) > best_len:
                best_len = len(t)
                best_div = div
        if best_div and best_len > 200:
            main_content = best_div
    
    # Запасной вариант — body целиком
    if not main_content:
        main_content = soup.body or soup
    
    # Получаем текст
    text = main_content.get_text(separator="\n", strip=True)
    
    # Убираем лишние пустые строки и короткие мусорные строки (меню, кнопки)
    lines = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Пропускаем строки-ссылки навигации (очень короткие одиночные слова без предложений)
        if len(line) < 3:
            continue
        lines.append(line)
    text = "\n".join(lines)
    
    body = (product_facts + "\n\n" + text).strip() if product_facts else text
    return candidate_links + body


async def _fetch_direct(session: aiohttp.ClientSession, url: str) -> Tuple[int, str]:
    """Прямой запрос к URL. Возвращает (status_code, html_or_error)."""
    async with session.get(url, allow_redirects=True, ssl=False) as resp:
        if resp.status != 200:
            return resp.status, ""
        content_type = resp.headers.get("Content-Type", "")
        if "text/html" not in content_type and "text/plain" not in content_type:
            return -1, f"[Невозможно прочитать: тип контента {content_type}]"
        html = await resp.text(errors="replace")
        return 200, html


async def _fetch_via_archive(session: aiohttp.ClientSession, url: str) -> Tuple[int, str]:
    """Попытка получить страницу через Wayback Machine (archive.org)."""
    archive_url = f"https://web.archive.org/web/2/{url}"
    try:
        async with session.get(archive_url, allow_redirects=True, ssl=False) as resp:
            if resp.status == 200:
                html = await resp.text(errors="replace")
                return 200, html
            return resp.status, ""
    except Exception:
        return -1, ""


# A dead proxy used to cost every page the full timeout. After a failure it is skipped for a while.
PROXY_TIMEOUT = 10
PROXY_COOLDOWN = 600
_proxy_down_until = 0.0

# Statuses that mean "we are not allowed", not "the page is gone".
BLOCK_STATUSES = {400, 401, 403, 407, 429, 498, 439}

# Marketplaces that refuse datacenter IPs (even a real Chromium gets the same wall), so their
# pages are pre-read for the model instead of being left to a tool call that always fails.
BOT_WALLED_HOSTS = (
    "ozon.ru", "ozon.by", "ozon.kz", "wildberries.ru", "wb.ru", "market.yandex.ru", "avito.ru",
    "aliexpress.ru", "megamarket.ru", "sbermegamarket.ru", "lamoda.ru", "citilink.ru", "dns-shop.ru",
)

_BOT_WALL_MARKERS = (
    "вы не робот", "подтвердите, что запросы отправляли вы", "похоже, нет соединения", "выключите vpn",
    "подозрительная активность", "доступ ограничен", "проблема с ip", "just a moment",
    "attention required", "are you not a robot", "verify you are human", "access denied", "enable javascript and cookies", "captcha", "антибот",
)


def is_bot_walled_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in BOT_WALLED_HOSTS)


def _looks_like_bot_wall(text: str) -> bool:
    """A short page that is a challenge or a block notice, not content (real pages are long)."""
    lowered = ' '.join((text or "").lower().split())
    return len(lowered) < 2500 and any(marker in lowered for marker in _BOT_WALL_MARKERS)


RU_MARKETPLACE_HOSTS = tuple(h for h in BOT_WALLED_HOSTS if h not in ("ozon.by", "ozon.kz")) + (
    "mvideo.ru", "eldorado.ru", "lemanapro.ru", "leroymerlin.ru",
    "chipdip.ru", "terraelectronica.ru", "promelec.ru", "compel.ru", "platan.ru",
)


def is_ru_marketplace(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
        return False
    try:
        if parsed.port not in (None, 80, 443):
            return False
    except ValueError:
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in RU_MARKETPLACE_HOSTS)


def _mark_listing_page(url: str, text: str) -> str:
    """Categories are discovery evidence, never a verified individual offer."""
    p=urlparse(url)
    host=(p.hostname or '').lower()
    listing = (
        (host=='ozon.ru' or host.endswith('.ozon.ru')) and p.path.startswith(('/category/','/search'))
        or (host in ('wildberries.ru','wb.ru') or host.endswith(('.wildberries.ru','.wb.ru'))) and p.path.startswith('/catalog/') and not re.fullmatch(r'/catalog/\d+/detail\.aspx',p.path,re.I)
        or (host=='market.yandex.ru' or host.endswith('.market.yandex.ru')) and p.path.startswith(('/search','/catalog','/offers/'))
    )
    if listing:
        return '[Подборка/поиск, НЕ проверенная карточка товара. Найди реальные ссылки на отдельные карточки, открой их и сравни предложения. Этот URL не подходит для готовой рекомендации или корзины.]\n\n'+text
    return text


async def _fetch_via_ru_proxy(session: aiohttp.ClientSession, url: str) -> Tuple[int, str]:
    """Попытка получить страницу через российский прокси-сервер."""
    global _proxy_down_until
    if not RU_PROXY_URL or time.time() < _proxy_down_until:
        return -1, ""
    try:
        async with session.get(
            url, allow_redirects=True, ssl=False, proxy=RU_PROXY_URL,
            timeout=aiohttp.ClientTimeout(total=PROXY_TIMEOUT),
        ) as resp:
            if resp.status != 200:
                return resp.status, ""
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return -1, f"[Невозможно прочитать: тип контента {content_type}]"
            html = await resp.text(errors="replace")
            return 200, html
    except Exception as e:
        _proxy_down_until = time.time() + PROXY_COOLDOWN
        logger.warning("RU proxy failed for %s (%s); skipping it for %ss", url, type(e).__name__, PROXY_COOLDOWN)
        return -1, ""


_URL_NOISE = {"product", "products", "category", "catalog", "catalogue", "item", "items", "dp", "itm", "p", "search", "html", "www"}


def _query_from_url(url: str) -> Tuple[str, str]:
    """(search query, SKU) guessed from a product or search URL: slugs read as words, long ids as SKU."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    brand = host.split(".")[0] if host else ""
    params = parse_qs(parsed.query)
    for key in ("text", "q", "query", "search", "searchtext"):
        if params.get(key):
            return f"{brand} {params[key][0]}".strip(), ""
    words, sku = [], ""
    for chunk in unquote(parsed.path).split("/"):
        for part in re.split(r"[-_+.]", chunk):
            if not part or part.lower() in _URL_NOISE:
                continue
            if part.isdigit() and len(part) >= 6:
                sku = sku or part
            elif len(part) > 1:
                words.append(part)
    return f"{brand} {' '.join(words[:14])}".strip(), sku


async def _recover_from_search(url: str) -> str:
    """The page itself is walled off for our server. The search index still knows the product."""
    try:
        from search_engine import search_web

        query, sku = _query_from_url(url)
        if not query:
            return ""
        results = await search_web(query, max_results=8)
        if not results and sku:
            results = await search_web(f"{query} {sku}", max_results=8)
    except Exception as exc:
        logger.info("Search recovery failed for %s: %s", url, exc)
        return ""
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    base = ".".join(host.split(".")[-2:])
    same = [r for r in results if base and base in (urlparse(r.get("url") or "").hostname or "")]
    exact = [r for r in same if sku and sku in (r.get("url") or "")]
    picked = (exact + [r for r in same if r not in exact] + [r for r in results if r not in same])[:6]
    if not picked:
        return ""
    lines = [
        f"{i}. {(r.get('title') or '').strip()} – {(r.get('snippet') or '').strip()[:400]} ({r.get('url')})"
        for i, r in enumerate(picked, 1)
    ]
    return (
        f"[Сайт {host} закрыт от автоматического чтения с серверов (антибот-защита), саму страницу открыть "
        "не удалось. Ниже то, что поиск знает по этой ссылке: это может быть неполно и не заменяет сайт. "
        "Скажи человеку об этом прямо, не пиши «нет соединения»; для точных данных предложи прислать текст "
        "страницы или скриншот.]\n\nЗапрос: " + query + "\n" + "\n".join(lines)
    )


def _is_fetch_failure(text: str) -> bool:
    stripped = (text or "").lstrip()
    return stripped.startswith(("[Ошибка", "[Страница пуста", "[Невозможно прочитать"))


async def _recover_with_kimi_fetch(url: str) -> str:
    try:
        from kimi_web_search import kimi_fetch

        fetched = await kimi_fetch(url)
        markdown = (fetched or {}).get("markdown") or ""
        if not markdown.strip() or _looks_like_bot_wall(markdown):
            return ""
        if len(markdown) > MAX_CONTENT_PER_URL:
            return markdown[:MAX_CONTENT_PER_URL] + "\n\n[...текст обрезан...]"
        return markdown
    except Exception as exc:
        logger.info("Kimi fetch fallback failed for %s: %s", url, exc)
        return ""


async def _fetch_url_content_local(url: str) -> Tuple[str, str]:
    """
    Скачивает и очищает контент одной URL.
    Порядок: российский прокси для маркетплейсов, прямой запрос для остальных, поисковая выдача по ссылке
    (для сайтов с антиботом), веб-архив. Возвращает (url, текст) или (url, сообщение_об_ошибке).
    """
    try:
        timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            # Read Russian product pages from the RU IP on the first attempt.
            # Keep direct access as a fallback when the tunnel is unavailable.
            proxy_first = bool(RU_PROXY_URL) and is_ru_marketplace(url)
            if proxy_first:
                status, html = await _fetch_via_ru_proxy(session, url)
                if status == -1:
                    status, html = await _fetch_direct(session, url)
            else:
                status, html = await _fetch_direct(session, url)
            walled = status in BLOCK_STATUSES or (status == 200 and _looks_like_bot_wall(_clean_html(html)))

            if walled and not proxy_first:
                logger.info(f"HTTP {status} / bot wall for {url}, trying RU proxy...")
                proxy_status, proxy_html = await _fetch_via_ru_proxy(session, url)
                if proxy_status == 200 and not _looks_like_bot_wall(_clean_html(proxy_html)):
                    status, html, walled = proxy_status, proxy_html, False

            if walled:
                recovered = await _recover_from_search(url)
                if recovered:
                    return url, recovered
                return url, (
                    "[Сайт защищён от автоматического чтения и не открылся. Скажи об этом прямо, "
                    "не пиши «нет соединения»; предложи прислать текст страницы или скриншот.]"
                )

            note = ""
            if status != 200 or not html:
                logger.info(f"Trying Wayback Machine for {url}...")
                status, html = await _fetch_via_archive(session, url)
                if status == 200 and html:
                    note = "[Копия из веб-архива, может быть устаревшей]\n"

            if status != 200 or not html:
                if status == -1 and html:
                    return url, html  # content-type error
                return url, f"[Ошибка загрузки: HTTP {status}]"

        text = _clean_html(html, url)

        if not text or len(text) < 50:
            return url, "[Страница пуста или не содержит текста]"

        if len(text) > MAX_CONTENT_PER_URL:
            text = text[:MAX_CONTENT_PER_URL] + "\n\n[...текст обрезан...]"

        return url, note + text

    except asyncio.TimeoutError:
        return url, "[Ошибка: превышено время ожидания загрузки страницы]"
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return url, f"[Ошибка загрузки: {str(e)[:100]}]"


async def fetch_url_content(url: str, *, use_kimi_fallback: bool = True) -> Tuple[str, str]:
    """Read marketplace pages at home when connected, then use existing fallbacks."""
    if is_ru_marketplace(url):
        try:
            from app.services.marketplace_relay import home_relay

            result = await home_relay.fetch(url)
            if result and result.get("status") == "ok":
                text = result.get("text", "").strip()
                if len(text) >= 50 and not _looks_like_bot_wall(text):
                    reviews = 'present' if 'ТЕКСТЫ ОТЗЫВОВ (' in text else 'not_extracted' if 'Тексты отзывов не извлечены:' in text else 'none' if 'На странице прямо указано отсутствие отзывов:' in text else 'unknown'
                    reader_audit.info('marketplace_read host=%s path=%s reader=home status=ok chars=%s review_texts=%s', urlparse(url).hostname, urlparse(url).path, len(text), reviews)
                    return url, _mark_listing_page(url, text[:MAX_CONTENT_PER_URL])
            reader_audit.info('marketplace_read host=%s path=%s reader=home status=%s fallback=server', urlparse(url).hostname, urlparse(url).path, (result or {}).get('status', 'unavailable'))
        except Exception as exc:
            logger.info("Home reader unavailable (%s), using server fallback", type(exc).__name__)
    fetched_url, text = await _fetch_url_content_local(url)
    if use_kimi_fallback and _is_fetch_failure(text):
        recovered = await _recover_with_kimi_fetch(url)
        if recovered:
            return fetched_url or url, recovered
    return fetched_url, _mark_listing_page(fetched_url or url, text)


async def process_urls_in_text(text: str) -> str:
    """
    Находит все URL в тексте, скачивает их содержимое
    и возвращает обогащённый текст, где после каждой ссылки 
    вставлено содержимое страницы.
    
    Если ссылок нет, возвращает исходный текст без изменений.
    """
    urls = find_urls(text)
    
    if not urls:
        return text
    
    # Скачиваем все URL параллельно
    tasks = [fetch_url_content(url) for url in urls]
    results = await asyncio.gather(*tasks)
    
    # Формируем обогащённый текст
    enriched = text
    
    for url, content in results:
        # Вставляем содержимое ссылки после самой ссылки в оригинальном тексте
        replacement = f"{url}\n\n--- Содержимое ссылки {url} ---\n{content}\n--- Конец содержимого ---\n"
        enriched = enriched.replace(url, replacement, 1)
    
    return enriched


async def walled_links_context(text: str) -> str:
    """Pages from sites that refuse our server, read ahead of the model call.

    Ordinary links are left to the model's own tools. These ones always fail there, and the
    model then blames the connection, so what the search index knows about them is handed over."""
    urls = [u for u in find_urls(text or "") if is_bot_walled_host(u)][:3]
    if not urls:
        return ""
    results = await asyncio.gather(*(fetch_url_content(u) for u in urls))
    parts = [f"Ссылка: {fetched_url or u}\n{content}" for u, (fetched_url, content) in zip(urls, results)]
    return (
        "Человек прислал ссылки на сайты, закрытые от серверных запросов. Сервер уже попытался их прочитать; "
        "результат ниже. Опирайся на него и честно скажи, чего не хватает.\n\n" + "\n\n---\n\n".join(parts)
    )[:14_000]
