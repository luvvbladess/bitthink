"""Windows home reader: outbound HTTPS jobs, isolated persistent browser.

No listening ports, model API keys, shell commands from the server, or personal
browser profile. This file is also usable as a foreground diagnostic worker.
"""
import argparse
import asyncio
import ipaddress
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import socket
import sys
import time
from urllib.parse import urlparse

DOMAINS = (
    "ozon.ru", "wildberries.ru", "wb.ru", "market.yandex.ru", "avito.ru",
    "aliexpress.ru", "megamarket.ru", "sbermegamarket.ru", "lamoda.ru",
    "citilink.ru", "dns-shop.ru", "mvideo.ru", "eldorado.ru", "lemanapro.ru", "leroymerlin.ru",
    "chipdip.ru", "terraelectronica.ru", "promelec.ru", "compel.ru", "platan.ru",
)
WALLS = (
    "вы не робот", "подтвердите, что запросы отправляли вы", "похоже, нет соединения",
    "проверяем браузер", "запросы, поступающие с вашего ip", "подозрительная активность",
    "доступ к сервису временно запрещён", "доступ ограничен", "just a moment",
    "are you not a robot", "verify you are human", "antibot", "captcha", "access denied",
)
MAX_TEXT = 80_000
logger = logging.getLogger("home-reader")


def marketplace_url(url):
    try:
        p = urlparse(url)
        host = (p.hostname or "").lower().rstrip(".")
        return p.scheme == "https" and not p.username and not p.password and p.port in (None, 443) and any(
            host == d or host.endswith("." + d) for d in DOMAINS
        )
    except ValueError:
        return False


def bot_wall(text):
    text = " ".join(text.lower().split())
    return len(text) < 3000 and any(marker in text for marker in WALLS)


def challenge_url(url):
    """Allow Yandex's separate CAPTCHA navigation only, never unrelated pages."""
    p = urlparse(url)
    return p.scheme == 'https' and not p.username and not p.password and p.hostname in ('yandex.ru', 'www.yandex.ru') and p.path.startswith(('/showcaptcha', '/checkcaptcha', '/captcha/'))


def public_host_sync(host):
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global for item in addresses)
    except (socket.gaierror, ValueError):
        return False


class Reader:
    def __init__(self, context):
        self.context = context
        self.public_cache = {}
        self.blocked_pages = {}

    async def route(self, route):
        parsed = urlparse(route.request.url)
        if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
            await route.abort()
            return
        try:
            if parsed.port not in (None, 80, 443):
                await route.abort()
                return
        except ValueError:
            await route.abort()
            return
        host = parsed.hostname or ""
        # Top-level frames stay within the marketplace allowlist. Public CDN
        # resources are allowed, but local/private network resources are blocked.
        request = route.request
        if request.is_navigation_request() and request.frame == request.frame.page.main_frame and not (marketplace_url(request.url) or challenge_url(request.url)):
            await route.abort()
            return
        cached = self.public_cache.get(host)
        if not cached or time.monotonic() - cached[0] > 60:
            safe = await asyncio.to_thread(public_host_sync, host)
            self.public_cache[host] = (time.monotonic(), safe)
        else:
            safe = cached[1]
        if safe:
            await route.continue_()
        else:
            await route.abort()

    async def fetch(self, url):
        if not marketplace_url(url):
            return {"status": "error", "url": url, "text": "", "title": ""}
        host = next(d for d in DOMAINS if (urlparse(url).hostname or '').rstrip('.') == d
                    or (urlparse(url).hostname or '').rstrip('.').endswith('.' + d))
        page = self.blocked_pages.pop(host, None)
        if page is None or page.is_closed():
            page = await self.context.new_page()
        keep_for_person = False
        try:
            response = None
            if page.url != url:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            # Give hydrated product details and automatic browser checks time.
            # A CAPTCHA is left for the person; it is never submitted by code.
            text = ""
            await page.wait_for_timeout(2000)
            for _ in range(10):
                await page.wait_for_timeout(1000)
                text = await page.locator("body").inner_text(timeout=3000)
                if len(text.strip()) >= 200 and not bot_wall(text):
                    break
            if not (marketplace_url(page.url) or challenge_url(page.url)):
                return {"status": "error", "url": url, "text": "", "title": ""}
            title = (await page.title())[:500]
            blocked = challenge_url(page.url) or bot_wall(text) or (response and response.status in (400, 401, 403, 429, 498, 439))
            if blocked:
                logger.warning("Площадка показала защиту: %s. Нужна ручная проверка в браузере Bit-Think.", urlparse(url).hostname)
                previous = self.blocked_pages.get(host)
                if previous and previous != page and not previous.is_closed():
                    await previous.close()
                if len(self.blocked_pages) >= 4 and host not in self.blocked_pages:
                    old_key = next(iter(self.blocked_pages))
                    old_page = self.blocked_pages.pop(old_key)
                    if not old_page.is_closed():
                        await old_page.close()
                self.blocked_pages[host] = page
                keep_for_person = True
                return {"status": "blocked", "url": url, "text": "", "title": title}
            # Preserve structured offers/ratings even if they are not in visible text.
            metadata = await page.locator('script[type="application/ld+json"]').evaluate_all(
                "els => els.map(e => e.textContent.slice(0, 80000)).slice(0, 10)"
            )
            facts = []
            def visit(item):
                if isinstance(item, list):
                    for child in item:
                        visit(child)
                elif isinstance(item, dict):
                    kinds = item.get("@type", [])
                    kinds = [kinds] if isinstance(kinds, str) else kinds
                    if isinstance(kinds, list) and any(str(k).rsplit('/', 1)[-1] == 'Product' for k in kinds):
                        facts.append(json.dumps({k: item[k] for k in (
                            'name', 'description', 'sku', 'brand', 'offers', 'aggregateRating', 'review',
                        ) if k in item}, ensure_ascii=False))
                    for child in item.values():
                        if isinstance(child, (list, dict)):
                            visit(child)
            for raw in metadata:
                try:
                    visit(json.loads(raw))
                except (ValueError, TypeError, RecursionError):
                    continue
            if facts:
                text = "Данные товара из страницы (JSON-LD):\n" + "\n".join(facts) + "\n\n" + text
            readable = len(text.strip()) >= 50
            text = (title + "\n\n" + text.strip())[:MAX_TEXT]
            logger.info("Прочитана страница %s: %s символов", urlparse(url).hostname, len(text))
            return {"status": "ok" if readable else "error", "url": page.url, "text": text, "title": title}
        except Exception as exc:
            logger.warning("Ошибка чтения %s (%s)", urlparse(url).hostname, type(exc).__name__)
            return {"status": "error", "url": url, "text": "", "title": ""}
        finally:
            if not keep_for_person and not page.is_closed():
                await page.close()


def browser_channel():
    bases = [os.environ.get('PROGRAMFILES', ''), os.environ.get('PROGRAMFILES(X86)', ''), os.environ.get('LOCALAPPDATA', '')]
    for relative, channel in [('Google/Chrome/Application/chrome.exe', 'chrome'), ('Microsoft/Edge/Application/msedge.exe', 'msedge')]:
        if any(base and (Path(base) / relative).is_file() for base in bases):
            return channel
    return None


async def run_session(config, directory):
    import aiohttp
    from playwright.async_api import async_playwright

    headers = {"Authorization": "Bearer " + config["token"]}
    base = config["server_url"].rstrip('/') + '/api/marketplace-relay'
    timeout = aiohttp.ClientTimeout(total=35)
    stop = asyncio.Event()
    async with aiohttp.ClientSession(headers=headers, timeout=timeout, trust_env=False) as session:
        async with async_playwright() as playwright:
            context = await playwright.chromium.launch_persistent_context(
                str(directory / 'browser-profile'), channel=browser_channel(),
                headless=bool(config.get('headless', False)), locale='ru-RU',
                viewport={"width": 1366, "height": 900},
                args=['--no-proxy-server', '--start-minimized'],
                service_workers='block', accept_downloads=False,
            )
            reader = Reader(context)
            await context.route('**/*', reader.route)
            context.on('close', lambda: stop.set())
            async def heartbeat():
                while not stop.is_set():
                    async with session.post(base + '/heartbeat') as response:
                        response.raise_for_status()
                    await asyncio.sleep(10)
            async def worker():
                while not stop.is_set():
                    async with session.get(base + '/jobs') as response:
                        response.raise_for_status()
                        job = (await response.json()).get('job')
                    if job:
                        result = await reader.fetch(job['url'])
                        async with session.post(base + '/jobs/' + job['id'], json=result) as response:
                            if response.status != 410:
                                response.raise_for_status()
            async def check_stop():
                while not (directory / 'stop.flag').exists() and not stop.is_set():
                    await asyncio.sleep(1)
                stop.set()
            async with session.post(base + '/heartbeat') as response:
                response.raise_for_status()
            logger.info("Подключено к Bit-Think. Ожидаю ссылки на товары.")
            tasks = [asyncio.create_task(heartbeat()), asyncio.create_task(worker()), asyncio.create_task(worker()), asyncio.create_task(check_stop())]
            tasks.append(asyncio.create_task(stop.wait()))
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await context.close()
                if (directory / 'stop.flag').exists():
                    try:
                        async with session.post(base + '/disconnect', timeout=aiohttp.ClientTimeout(total=5)) as response:
                            await response.read()
                    except Exception:
                        pass


async def main_loop(config, directory):
    while not (directory / 'stop.flag').exists():
        try:
            await run_session(config, directory)
        except Exception as exc:
            logger.warning("Соединение прервано (%s). Повтор через 10 секунд.", type(exc).__name__)
        if not (directory / 'stop.flag').exists():
            await asyncio.sleep(10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.json')))
    args = parser.parse_args()
    path = Path(args.config).resolve()
    directory = path.parent
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    if config.get('server_url') != 'https://bit-think.space' or len(config.get('token', '')) < 32:
        raise ValueError('Invalid home reader configuration')
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(directory / 'agent.log', maxBytes=1_000_000, backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
    if sys.stdout:
        logger.addHandler(logging.StreamHandler())
    # One worker process per installation, including repeated Start clicks.
    lock = open(directory / 'agent.lock', 'a+b')
    if os.name == 'nt':
        import msvcrt
        if lock.tell() == 0:
            lock.write(b'1'); lock.flush()
        lock.seek(0)
        try:
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            return
    try:
        asyncio.run(main_loop(config, directory))
    finally:
        lock.close()


if __name__ == '__main__':
    if getattr(sys, 'frozen', False) and '--worker' not in sys.argv:
        from windows_setup import setup_main

        setup_main()
    else:
        if '--worker' in sys.argv:
            sys.argv.remove('--worker')
        main()
