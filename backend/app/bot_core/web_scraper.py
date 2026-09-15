"""
Модуль для извлечения содержимого веб-страниц из ссылок в сообщениях.
Находит все URL в тексте, скачивает контент и подставляет его в запрос.
"""

import re
import logging
import asyncio
from typing import List, Optional, Tuple

import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

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


def _clean_html(html: str) -> str:
    """Извлекает чистый текст из HTML, удаляя скрипты, стили и навигацию."""
    soup = BeautifulSoup(html, "html.parser")
    
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
    
    return text


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


async def _fetch_via_google_cache(session: aiohttp.ClientSession, url: str) -> Tuple[int, str]:
    """Попытка получить страницу через кеш Google."""
    cache_url = f"https://webcache.googleusercontent.com/search?q=cache:{url}"
    try:
        async with session.get(cache_url, allow_redirects=True, ssl=False) as resp:
            if resp.status == 200:
                html = await resp.text(errors="replace")
                return 200, html
            return resp.status, ""
    except Exception:
        return -1, ""


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


async def _fetch_via_ru_proxy(session: aiohttp.ClientSession, url: str) -> Tuple[int, str]:
    """Попытка получить страницу через российский прокси-сервер."""
    try:
        async with session.get(url, allow_redirects=True, ssl=False, proxy=RU_PROXY_URL) as resp:
            if resp.status != 200:
                return resp.status, ""
            content_type = resp.headers.get("Content-Type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return -1, f"[Невозможно прочитать: тип контента {content_type}]"
            html = await resp.text(errors="replace")
            return 200, html
    except Exception as e:
        logger.warning(f"RU proxy failed for {url}: {e}")
        return -1, ""


async def fetch_url_content(url: str) -> Tuple[str, str]:
    """
    Скачивает и очищает контент одной URL.
    При ошибке 403 (гео-блокировка) пробует альтернативные источники.
    Возвращает (url, текст_контента) или (url, сообщение_об_ошибке).
    """
    try:
        timeout = aiohttp.ClientTimeout(total=FETCH_TIMEOUT)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            # 1. Прямой запрос
            status, html = await _fetch_direct(session, url)
            
            # 2. Если 403 (гео-блок) — пробуем через российский прокси
            if status == 403:
                logger.info(f"HTTP 403 for {url}, trying RU proxy...")
                status, html = await _fetch_via_ru_proxy(session, url)
            
            # 3. Если прокси не помог — пробуем Google Cache
            if status != 200 or not html:
                logger.info(f"Trying Google Cache for {url}...")
                status, html = await _fetch_via_google_cache(session, url)
            
            # 4. Последний шанс — archive.org
            if status != 200 or not html:
                logger.info(f"Trying Wayback Machine for {url}...")
                status, html = await _fetch_via_archive(session, url)
            
            # 4. Если ничего не помогло
            if status != 200 or not html:
                if status == 403:
                    return url, "[Ошибка: сайт заблокировал доступ (HTTP 403). Попробуйте скопировать текст страницы и отправить его напрямую.]"
                elif status == -1 and html:
                    return url, html  # content-type error
                else:
                    return url, f"[Ошибка загрузки: HTTP {status}]"
        
        text = _clean_html(html)
        
        if not text or len(text) < 50:
            return url, "[Страница пуста или не содержит текста]"
        
        # Обрезаем до лимита
        if len(text) > MAX_CONTENT_PER_URL:
            text = text[:MAX_CONTENT_PER_URL] + "\n\n[...текст обрезан...]"
        
        return url, text
        
    except asyncio.TimeoutError:
        return url, "[Ошибка: превышено время ожидания загрузки страницы]"
    except Exception as e:
        logger.error(f"Error fetching {url}: {e}")
        return url, f"[Ошибка загрузки: {str(e)[:100]}]"


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
