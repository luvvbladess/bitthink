import asyncio
import json
import pytest
from app.services import server_search as search
from app.services.run_protocol import RunRecord, current_run
from app.bot_core.turn_scope import turn_conversation, page_reads


def test_slow_primary_does_not_delay_useful_free_fallback(monkeypatch):
    cancelled = []
    async def fetch(provider, query):
        if provider == 'duckduckgo':
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                cancelled.append(provider)
                raise
        return [{'title': f'G435 {i}', 'url': f'https://example.com/g435/{i}', 'snippet': 'Данные выдачи'} for i in range(3)], 'ok'
    monkeypatch.setattr(search, '_fetch', fetch)
    async def run():
        result = await asyncio.wait_for(search.server_search('G435'), 1.5)
        assert len(result['results']) == 3 and not result['paid_api_used']
        assert result['engines']['duckduckgo'] == 'cancelled_after_results'
        cached = await search.server_search('  g435  ')
        assert cached['cached'] and all(row['cached'] for row in cached['results'])
        assert result['retrieved_at'] == cached['retrieved_at']
    asyncio.run(run())
    assert cancelled == ['duckduckgo']


def test_shared_page_read_survives_one_waiter_cancel_but_not_next_turn(monkeypatch):
    import web_scraper
    calls = []
    async def fetch(url, **kwargs):
        calls.append(url)
        await asyncio.sleep(0.02)
        return 'https://ozon.ru/product/thing-123/', 'Данные карточки ' * 20
    monkeypatch.setattr(web_scraper, '_fetch_url_content_once', fetch)
    async def run():
        with turn_conversation('one'):
            first = asyncio.create_task(web_scraper.fetch_url_content('https://ozon.ru/t/abc'))
            second = asyncio.create_task(web_scraper.fetch_url_content('https://ozon.ru/t/abc'))
            await asyncio.sleep(0.001)
            first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            result = await second
            assert await web_scraper.fetch_url_content(result[0]) == result
            assert len(calls) == 1
        assert page_reads() is None
        with turn_conversation('two'):
            await web_scraper.fetch_url_content('https://ozon.ru/t/abc')
        assert len(calls) == 2
    asyncio.run(run())


def test_full_read_never_reuses_partial_overview(monkeypatch):
    import web_scraper
    from app.bot_core.turn_scope import _reader_mode
    calls = []
    async def fetch(url, **kwargs):
        calls.append(url)
        return url, 'Данные ' * 20
    monkeypatch.setattr(web_scraper, '_fetch_url_content_once', fetch)
    async def run():
        with turn_conversation('one', reader_detail='overview'):
            await web_scraper.fetch_url_content('https://ozon.ru/product/a-1/')
            token = _reader_mode.set('full')
            try: await web_scraper.fetch_url_content('https://ozon.ru/product/a-1/')
            finally: _reader_mode.reset(token)
        assert len(calls) == 2
    asyncio.run(run())


def test_evidence_preserves_identity_dates_and_prioritizes_real_reads():
    from handlers.core import _merge_sources
    record = RunRecord()
    record.observe_search([{'title': str(i), 'url': f'https://example.com/{i}', 'snippet': 'Цена из выдачи'} for i in range(30)], '2026-10-01T01:00:00Z', cached=True)
    source_id = record.sources[-1]['id']
    record.observe_page('URL: https://example.com/29\n\n' + 'Данные из карточки ' * 10 + '\nТЕКСТЫ ОТЗЫВОВ (2): отзывы')
    assert len(record.sources) == 30 and record.sources[-1]['id'] == source_id
    assert record.sources[-1]['status'] == 'read' and not record.sources[-1]['cached']
    rows = _merge_sources(record.enrich_sources([]), [], limit=10)
    assert rows[0]['summary'].startswith('https://example.com/29\n')
    assert rows[0]['reviews_state'] == 'read'
    assert rows[1]['cached'] and rows[1]['read_at'] == '2026-10-01T01:00:00Z'
    data = json.loads(record.evidence_prompt().split('\n')[-1])
    assert data['sources'][-1]['status'] == 'read'
    record.observe_page('URL: https://example.com/29\n\n[Ошибка загрузки]')
    assert record.sources[-1]['status'] == 'failed' and record.sources[-1]['reviews'] == 'unknown'


def test_pasted_url_fetch_is_observed_without_fabricated_tool_call(monkeypatch):
    import web_scraper
    async def transport(url, **kwargs): return url, '[Копия из веб-архива, может быть устаревшей]\n' + 'Содержание ' * 10
    monkeypatch.setattr(web_scraper, '_fetch_url_content_transport', transport)
    async def run():
        record = RunRecord(); token = current_run.set(record)
        try:
            await web_scraper.fetch_url_content('https://example.com/a')
            assert record.sources[0]['origin'] == 'archive'
            assert not record.tools
        finally: current_run.reset(token)
    asyncio.run(run())


def test_antibot_error_never_counts_as_page_read():
    record = RunRecord()
    record.observe_page('URL: https://example.com/a\n\n[Сайт защищён от автоматического чтения и не открылся. Скажи об этом прямо.]')
    assert record.sources[0]['status'] == 'failed'
