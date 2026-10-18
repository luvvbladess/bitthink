import asyncio
import json
from urllib.parse import quote

import pytest
from app.config import get_settings  # noqa: F401
from app.services import server_search as search
from app.services.run_protocol import RunRecord, current_run


HTML = '''<div class="result"><h2><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fozon.ru%2Fproduct%2Fg435-123%2F">Logitech G435 — отзывы Ozon</a></h2><a class="result__snippet">Рейтинг 4,8. Текст поисковой выдачи.</a></div>
<div class="result result--ad"><a class="result__a" href="https://ads.example.com">Реклама</a></div>
<div class="result"><a class="result__a" href="javascript:alert(1)">Неправильная ссылка</a></div>'''
RSS = '''<rss><channel><item><title>G435 в магазине</title><link>https://shop.example.com/g435</link><description>Цена в выдаче</description></item><item><title>private</title><link>http://127.0.0.1/private</link></item></channel></rss>'''


def test_parsers_keep_real_product_links_skip_ads_and_private_targets():
    rows = search.parse_ddg(HTML)
    assert len(rows) == 1
    assert rows[0]['url'] == 'https://ozon.ru/product/g435-123/'
    assert rows[0]['provider'] == 'duckduckgo'
    assert len(search.parse_bing(RSS)) == 1
    assert search.safe_result_url('https://example.com/?token=secret') == ''
    assert search.safe_result_url('http://localhost/x') == ''
    assert search.safe_result_url('http://192.168.1.1/x') == ''


def test_rank_filters_exact_model_and_requested_store():
    rows = search.parse_ddg(HTML) + search.parse_bing(RSS) + [{'title': 'Logitech homepage', 'url': 'https://logitech.com/', 'snippet': 'Logitech G HUB'}]
    result = search.rank_results(rows, 'Logitech G435 отзывы', ['ozon.ru'])
    assert len(result) == 1 and 'g435-123' in result[0]['url']
    assert search.rank_results(rows, 'другой товар TL072', []) == []


def test_ambiguous_name_without_query_context_is_not_a_result():
    rows = [
        {'title':'Melissa shoes 2026', 'url':'https://shopmelissa.com/', 'snippet':'Jelly shoes and sandals'},
        {'title':'Mobile used cars', 'url':'https://mobile.de/', 'snippet':'Cars for sale'},
        {'title':'Melissa win rate in Mobile Legends', 'url':'https://mlbb.example/heroes/melissa', 'snippet':'Ranked statistics'},
    ]
    results = search.rank_results(rows, 'Melissa Mobile Legends winrate 2026', [])
    assert len(results) == 1 and results[0]['url'].startswith('https://mlbb.example/')
    assert search.rank_results(rows[:2], 'Melissa Mobile Legends winrate 2026', []) == []


def test_product_homepage_is_not_enough_for_specific_plan_pricing():
    rows = [
        {'title':'GitHub homepage', 'url':'https://github.com/', 'snippet':'GitHub Copilot for programming'},
        {'title':'GitHub Copilot Pro pricing', 'url':'https://github.com/features/copilot/plans', 'snippet':'Paid plan'},
    ]
    assert search.rank_results(rows, 'GitHub Copilot Pro pricing', []) == [rows[1]]


def test_exact_component_identifier_does_not_need_generic_query_words():
    rows = [{'title':'TL072', 'url':'https://shop.example/tl072', 'snippet':'Available'}]
    assert search.rank_results(rows, 'найди купить операционный усилитель TL072', []) == rows


def test_search_is_single_flight_cached_and_never_opens_result_pages(monkeypatch):
    calls = []
    async def fetch(provider, query):
        calls.append((provider, query))
        await asyncio.sleep(0.01)
        return [{'title': f'Logitech G435 {i}', 'url': f'https://ozon.ru/product/g435-{i}', 'snippet': 'Текст выдачи'} for i in range(4)], 'ok'
    monkeypatch.setattr(search, '_fetch', fetch)
    async def run():
        record = RunRecord()
        token = current_run.set(record)
        try:
            results = await asyncio.gather(*(search.server_search('Logitech G435', sites=['ozon.ru']) for _ in range(3)))
            again = await search.server_search('Logitech G435', limit=2, sites=['ozon.ru'])
            assert again['cached'] and len(again['results']) == 2
            assert all(source['status'] == 'retrieved' and not source['excerpt'] for source in record.sources)
            assert len(record.sources) == 4
            return results
        finally:
            current_run.reset(token)
    results = asyncio.run(run())
    assert len(calls) == 1 and 'site:ozon.ru' in calls[0][1]
    assert all(not r['paid_api_used'] for r in results)


def test_blocked_provider_uses_free_fallback_not_paid_api(monkeypatch):
    calls = []
    async def fetch(provider, query):
        calls.append(provider)
        return ([], 'limited') if provider == 'duckduckgo' else (search.parse_bing(RSS), 'ok')
    monkeypatch.setattr(search, '_fetch', fetch)
    result = asyncio.run(search.server_search('G435 цена'))
    assert calls == ['duckduckgo', 'bing']
    assert result['results'] and result['paid_api_used'] is False


def test_invalid_or_unavailable_search_is_honest(monkeypatch):
    async def unavailable(provider, query):
        return [], 'unavailable'
    monkeypatch.setattr(search, '_fetch', unavailable)
    async def run():
        assert (await search.server_search(''))['status'] == 'invalid_query'
        assert (await search.server_search('x' * 501))['status'] == 'invalid_query'
        assert (await search.server_search('test', sites=['http://127.0.0.1']))['status'] == 'invalid_sites'
        result = await search.server_search('G435')
        assert result['status'] == 'unavailable' and result['results'] == []
    asyncio.run(run())


def test_default_search_paths_do_not_call_paid_apis_or_auto_crawl(monkeypatch):
    import search_engine, kimi_web_search
    monkeypatch.delenv('WEB_SEARCH_BACKEND', raising=False)
    calls = []
    async def fake_server(query, **kwargs):
        calls.append(query)
        return {'results': [{'title': 'G435', 'url': 'https://ozon.ru/product/g435', 'snippet': 'Данные из поиска'}], 'status': 'ok'}
    async def forbidden(*args, **kwargs):
        raise AssertionError('Paid API or automatic page read must not run')
    monkeypatch.setattr(search, 'server_search', fake_server)
    monkeypatch.setattr(search_engine, '_search_kimi_sources', forbidden)
    monkeypatch.setattr(search_engine, '_search_kimi_pro', forbidden)
    monkeypatch.setattr(search_engine, '_search_openai_sources', forbidden)
    monkeypatch.setattr(search_engine, 'fetch_url_content', forbidden)
    monkeypatch.setattr(kimi_web_search, '_post_json', forbidden)
    async def run():
        assert await search_engine.search_web('G435')
        assert await kimi_web_search.kimi_search('G435')
        assert await kimi_web_search.kimi_search_pro('G435', sites=['ozon.ru'])
        text, sources = await search_engine.build_grounded_web_context('G435')
        assert 'Данные из поиска' in text and sources
        assert 'Сниппет' in await search_engine.smart_web_search('G435')
    asyncio.run(run())
    assert len(calls) == 5


def test_cancelled_waiter_does_not_cancel_shared_search_or_leak_pending(monkeypatch):
    async def fetch(*args):
        await asyncio.sleep(0.02)
        return search.parse_ddg(HTML), 'ok'
    monkeypatch.setattr(search, '_fetch', fetch)
    async def run():
        first = asyncio.create_task(search.server_search('G435'))
        second = asyncio.create_task(search.server_search('G435'))
        await asyncio.sleep(0.001)
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        assert (await second)['results']
        assert not search.state().pending
    asyncio.run(run())


def test_empty_overqualified_query_has_one_bounded_free_recovery(monkeypatch):
    calls=[]
    async def fetch(query,sites):
        calls.append((query,sites))
        rows=[] if '2026' in query else [{'title':'Current stats','url':'https://example.com/stats','snippet':'Live table'}]
        return dict(results=rows,status='ok' if rows else 'empty',engines={'bing':'ok' if rows else 'empty'},paid_api_used=False)
    monkeypatch.setattr(search,'_search',fetch)
    result=asyncio.run(search._search_with_recovery('Melissa MLBB win rate current patch 2026',['example.com']))
    assert len(calls)==2 and calls[1]==('Melissa MLBB win rate',['example.com'])
    assert result['query_relaxed'] and result['freshness_verified'] is False
    assert result['paid_api_used'] is False


def test_recovery_preserves_model_ids_quotes_and_skips_provider_outage(monkeypatch):
    assert search.relaxed_query('GPT-2026 pricing')=='GPT-2026 pricing'
    assert search.relaxed_query('"2026 current patch" stats')=='"2026 current patch" stats'
    calls=[]
    async def blocked(query,sites):
        calls.append(query)
        return dict(results=[],status='unavailable',engines={'bing':'limited','duckduckgo':'unavailable'})
    monkeypatch.setattr(search,'_search',blocked)
    result=asyncio.run(search._search_with_recovery('Melissa current patch 2026',[]))
    assert len(calls)==1 and result['status']=='unavailable'
