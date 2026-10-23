"""Bounded server-side metasearch. No paid API, account, browser or page crawl.

Public result pages can rate-limit us. Empty/blocked results stay empty rather
than silently invoking a paid provider. Search snippets are not page evidence.
"""
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import asyncio
import ipaddress
import os
import re
import time
from urllib.parse import urlsplit, urlunsplit, parse_qs
from xml.etree import ElementTree as ET

import aiohttp
from bs4 import BeautifulSoup

MAX_QUERY = 500
MAX_BYTES = 1500000
TTL = 180
MAX_CACHE = 256
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; BitThinkSearch/1.0)',
           'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.7'}


from contextvars import ContextVar

orchestrator_search = ContextVar("orchestrator_server_search", default=False)


def use_server_search() -> bool:
    return orchestrator_search.get() or os.getenv('WEB_SEARCH_BACKEND', 'server').strip().lower() == 'server'


def safe_result_url(value: str) -> str:
    if value.startswith('//'):
        value = 'https:' + value
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower()
        if host == 'duckduckgo.com' or host.endswith('.duckduckgo.com'):
            target = parse_qs(parsed.query).get('uddg', [''])[0]
            if not target:
                return ''
            return safe_result_url(target)
        if parsed.scheme not in {'http', 'https'} or not host or parsed.username or parsed.password:
            return ''
        if host == 'localhost' or host.endswith(('.localhost', '.local')) or '.' not in host:
            return ''
        try:
            if not ipaddress.ip_address(host).is_global:
                return ''
        except ValueError:
            pass
        from app.services.run_protocol import public_url
        return public_url(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, '')))
    except ValueError:
        return ''


def parse_ddg(body: str) -> list[dict]:
    soup = BeautifulSoup(body, 'html.parser')
    rows = []
    for result in soup.select('.result'):
        anchor = result.select_one('a.result__a')
        if not anchor or 'result--ad' in result.get('class', []):
            continue
        url = safe_result_url(anchor.get('href', ''))
        if not url:
            continue
        snippet = result.select_one('.result__snippet')
        rows.append({'title': anchor.get_text(' ', strip=True)[:240], 'url': url,
                     'snippet': snippet.get_text(' ', strip=True)[:1000] if snippet else '', 'provider': 'duckduckgo'})
    return rows[:20]


def parse_bing(body: str) -> list[dict]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    rows = []
    for result in root.findall('./channel/item'):
        url = safe_result_url(result.findtext('link') or '')
        if url:
            rows.append({'title': (result.findtext('title') or '')[:240], 'url': url,
                         'snippet': BeautifulSoup(result.findtext('description') or '', 'html.parser').get_text(' ', strip=True)[:1000],
                         'provider': 'bing'})
    return rows[:20]


def _term_matches(term: str, text: str) -> bool:
    if re.fullmatch(r'[a-z0-9-]+', term):
        return re.search(r'(?<![a-z0-9])' + re.escape(term) + r'(?![a-z0-9])', text) is not None
    return term in text


def rank_results(rows: list[dict], query: str, sites: list[str]) -> list[dict]:
    keywords = set(re.findall(r'[a-zа-яё0-9-]{3,}', query.lower())) - {'найди', 'покажи', 'какой', 'какая', 'есть', 'site', 'https', 'www', 'com', 'org', 'net'}
    keywords = {term for term in keywords if not re.fullmatch(r'20\d{2}', term)}
    models = re.findall(r'\b(?=[a-z0-9-]*[a-z])(?=[a-z0-9-]*\d)[a-z0-9-]+\b', query.lower())
    found = {}
    for index, row in enumerate(rows):
        url = row['url']
        host = urlsplit(url).hostname or ''
        if sites and not any(host == site or host.endswith('.' + site) for site in sites):
            continue
        text = ' '.join(str(row.get(k) or '') for k in ('title', 'url', 'snippet')).lower()
        if models and not any(model in text or model.replace('-', '') in text.replace('-', '') for model in models):
            continue
        score = sum(2 if _term_matches(term, row['title'].lower()) else 1 for term in keywords if _term_matches(term, text))
        matched = sum(_term_matches(term, text) for term in keywords)
        # A multi-term question cannot be satisfied by just its ambiguous name:
        # "Melissa Mobile Legends winrate" previously admitted shoe shops.
        required = min(3, (len(keywords) * 3 + 4) // 5) if not models else 1
        if keywords and matched < required:
            continue
        if url not in found:
            found[url] = (score, -index, row)
    return [item[2] for item in sorted(found.values(), key=lambda value: (value[0], value[1]), reverse=True)]


@dataclass
class SearchState:
    loop: asyncio.AbstractEventLoop
    semaphore: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(3))
    cache: OrderedDict = field(default_factory=OrderedDict)
    pending: dict = field(default_factory=dict)


_state: SearchState | None = None


def state() -> SearchState:
    global _state
    loop = asyncio.get_running_loop()
    if _state is None or _state.loop is not loop:
        _state = SearchState(loop)
    return _state


async def _fetch(provider: str, query: str) -> tuple[list[dict], str]:
    url = 'https://html.duckduckgo.com/html/' if provider == 'duckduckgo' else 'https://www.bing.com/search'
    params = {'q': query, 'kl': 'ru-ru'} if provider == 'duckduckgo' else {'q': query, 'format': 'rss', 'setlang': 'ru-RU'}
    try:
        async with state().semaphore:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4.5)) as session:
                async with session.get(url, params=params, headers=HEADERS, allow_redirects=False) as response:
                    if response.status != 200:
                        return [], 'limited' if response.status in {202, 403, 429} else 'unavailable'
                    data = await response.content.read(MAX_BYTES + 1)
                    if len(data) > MAX_BYTES:
                        return [], 'unavailable'
                    body = data.decode('utf-8', errors='replace')
        rows = parse_ddg(body) if provider == 'duckduckgo' else parse_bing(body)
        return rows, 'ok' if rows else 'empty'
    except (aiohttp.ClientError, asyncio.TimeoutError):
        return [], 'unavailable'


async def _search(query: str, sites: list[str]) -> dict:
    qualified = query + (' (' + ' OR '.join('site:' + site for site in sites) + ')' if sites else '')
    statuses = {}
    tasks = {}
    received = {}
    useful = []
    try:
        async with asyncio.timeout(9):
            first = asyncio.create_task(_fetch('duckduckgo', qualified))
            tasks[first] = 'duckduckgo'
            done, _ = await asyncio.wait([first], timeout=0.25)
            if done:
                received['duckduckgo'], statuses['duckduckgo'] = first.result()
                useful = rank_results(received['duckduckgo'], query, sites)
            if len(useful) < 3:
                fallback = asyncio.create_task(_fetch('bing', qualified))
                tasks[fallback] = 'bing'
                pending = {t for t in tasks if tasks[t] not in received}
                while pending:
                    done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        provider = tasks[task]
                        received[provider], statuses[provider] = task.result()
                    rows = received.get('duckduckgo', []) + received.get('bing', [])
                    useful = rank_results(rows, query, sites)
                    if len(useful) >= 3:
                        break
    except asyncio.TimeoutError:
        statuses['deadline'] = 'timeout'
    finally:
        for task, provider in tasks.items():
            if not task.done():
                statuses[provider] = 'cancelled_after_results' if useful else 'timeout'
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    retrieved_at = datetime.now(timezone.utc).isoformat()
    return {'results': [{**row, 'evidence_state': 'retrieved', 'read_at': retrieved_at} for row in useful[:20]],
            'status': 'ok' if useful else 'unavailable' if any(v in {'unavailable', 'limited', 'timeout'} for v in statuses.values()) else 'empty',
            'engines': statuses, 'retrieved_at': retrieved_at, 'paid_api_used': False}


def relaxed_query(query: str) -> str:
    """One discovery fallback, never a relaxation of the user's factual criteria."""
    if any(char in query for char in ('"', '«', '»')):
        return query  # preserve quoted literals
    text=re.sub(r'\b(?:в\s+)?(?:текущ\w*|последн\w*|нов\w*)\s+патч\w*\b|'
                r'\b(?:current|latest|new)\s+patch\b|\b(?:сейчас|сегодня|актуальн\w*|currently|latest)\b', ' ',query,flags=re.I)
    text=re.sub(r'(?<![\w-])20\d{2}(?![\w-])(?:\s+год\w*)?', ' ',text,flags=re.I)
    text=' '.join(text.split()).strip(' ,;')
    return text if len(text)>=8 and len(text.split())>=2 else query


async def _search_with_recovery(query, sites):
    result=await _search(query,sites)
    alternative=relaxed_query(query)
    healthy=any(status in {'ok','empty'} for status in result.get('engines',{}).values())
    if not result['results'] and alternative!=query and (result.get('status')=='empty' or healthy):
        recovered=await _search(alternative,sites)
        if recovered['results']:
            return {**recovered,'query_relaxed':True,'discovery_query':alternative,
                    'freshness_verified':False,'initial_engines':result.get('engines',{})}
    return result


async def server_search(query: str, *, limit: int = 10, sites: list[str] | None = None) -> dict:
    try:
        limit = max(1, min(20, int(limit)))
    except (ValueError, TypeError):
        limit = 10
    text = ' '.join((query or '').split())
    if not text or len(text) > MAX_QUERY:
        return {'results': [], 'status': 'invalid_query', 'paid_api_used': False}
    domains = []
    for raw in (sites or [])[:5]:
        try:
            value = str(raw).strip().lower().removeprefix('www.').encode('idna').decode('ascii')
        except UnicodeError:
            continue
        if re.fullmatch(r'[a-z0-9][a-z0-9.-]*\.[a-z0-9-]{2,63}', value) and value not in domains:
            domains.append(value)
    if sites and not domains:
        return {'results': [], 'status': 'invalid_sites', 'paid_api_used': False}
    from app.billing.quota import assert_search_allowed
    await assert_search_allowed()
    key = (text.casefold(), tuple(sorted(domains)))
    current = state()
    cached = current.cache.get(key)
    if cached and time.monotonic() - cached[0] < (TTL if cached[1]['results'] else 15):
        result = {**cached[1], 'results': [{**row, 'cached': True} for row in cached[1]['results'][:limit]], 'cached': True}
        observe_results(result)
        return result
    task = current.pending.get(key)
    if task is None:
        if len(current.pending) >= 32:
            return {'results': [], 'status': 'busy', 'paid_api_used': False}
        task = asyncio.create_task(_search_with_recovery(text, domains))
        current.pending[key] = task
        task.add_done_callback(lambda _: current.pending.pop(key, None))
    try:
        result = await asyncio.shield(task)
        current.cache[key] = (time.monotonic(), result)
        current.cache.move_to_end(key)
        while len(current.cache) > MAX_CACHE:
            current.cache.popitem(last=False)
        result = {**result, 'results': [{**row, 'cached': False} for row in result['results'][:limit]], 'cached': False}
        observe_results(result)
        return result
    finally:
        if task.done():
            current.pending.pop(key, None)


def observe_results(result: dict) -> None:
    from app.services.run_protocol import current_run
    record = current_run.get()
    if record:
        record.observe_search(result.get('results', []), result.get('retrieved_at', ''), cached=result.get('cached', False))
