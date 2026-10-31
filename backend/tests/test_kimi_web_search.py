import asyncio
import pytest
from types import SimpleNamespace

from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path

import kimi_client
import kimi_web_search
import search_engine
import web_scraper


def test_search_brief_incorporates_last_tool_result_at_step_limit(monkeypatch):
    import computer_skills.loader
    monkeypatch.setattr(computer_skills.loader, 'match_skills', lambda *a, **k: [])
    monkeypatch.setattr(kimi_client, 'client', object())
    calls = []
    async def model(client, data, **kwargs):
        calls.append(data)
        if len(calls) <= 4:
            tool = SimpleNamespace(id=str(len(calls)), type='function', function=SimpleNamespace(name='browse_page', arguments='{}'))
            message = SimpleNamespace(content='Still checking', tool_calls=[tool])
        else:
            assert 'tools' not in data
            assert any('LAST_PAGE_STAT' in str(m.get('content')) for m in data['messages'])
            message = SimpleNamespace(content='Final statistic from LAST_PAGE_STAT', tool_calls=[])
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=None)
    async def append(messages, tools, **kwargs):
        messages.append({'role':'tool', 'tool_call_id':tools[0].id, 'content':'LAST_PAGE_STAT'})
        return []
    monkeypatch.setattr(kimi_client, 'model_call', model)
    monkeypatch.setattr(kimi_client, '_append_tool_results', append)
    answer = asyncio.run(kimi_client.get_kimi_search_brief([], 'Hero question'))
    assert answer == 'Final statistic from LAST_PAGE_STAT' and len(calls) == 5


@pytest.fixture(autouse=True)
def explicit_paid_provider_contract(monkeypatch):
    # These tests exercise the retained REST adapter, not the new free default.
    monkeypatch.setenv('WEB_SEARCH_BACKEND', 'kimi')


SAMPLE_BASIC = {
    "search_results": [
        {
            "authority": "S",
            "date": "2026-09-16",
            "icon": "",
            "mime": "text/html",
            "site_name": "Kimi",
            "snippet": "Standalone REST search endpoints",
            "text": "",
            "title": "New web search API",
            "url": "https://forum.moonshot.ai/t/new-web-search-api-is-now-avaliable/606",
        },
        {
            "authority": "S",
            "date": "2026-09-16",
            "icon": "",
            "mime": "text/html",
            "site_name": "Kimi",
            "snippet": "Ranked passages for RAG",
            "text": "",
            "title": "Web Search Pro",
            "url": "https://platform.kimi.ai/docs/api/tools-search-pro",
        },
    ]
}

SAMPLE_PRO = {
    "search_results": [
        {
            "authority": "S",
            "date": "2026-09-16",
            "icon": "",
            "mime": "text/html",
            "site_name": "Kimi API",
            "snippet": "Search Pro returns chunks",
            "title": "Web Search Pro docs",
            "url": "https://platform.kimi.ai/docs/api/tools-search-pro",
            "chunks": [
                {"text": "search_pro returns ranked passages", "score": 1.2},
                {"text": "sites and time_window constrain results", "score": 0.9},
            ],
        },
        {
            "authority": "S",
            "date": "2026-09-16",
            "icon": "",
            "mime": "text/html",
            "site_name": "Kimi Forum",
            "snippet": "Standalone REST search API announcement",
            "title": "New web search API",
            "url": "https://forum.moonshot.ai/t/new-web-search-api-is-now-avaliable/606",
            "chunks": [
                {"text": "Kimi Open Platform now offers search, search_pro, and fetch", "score": 1.1},
            ],
        },
    ]
}


def test_normalize_and_format_search_payloads():
    basic = kimi_web_search.normalize_search_results(SAMPLE_BASIC)
    assert len(basic) == 2
    sources = kimi_web_search.to_engine_sources(basic)
    assert sources[0]["url"].startswith("https://")
    assert "REST" in sources[0]["snippet"]

    pro = kimi_web_search.normalize_search_results(SAMPLE_PRO)
    rendered = kimi_web_search.format_results_for_model(pro)
    assert "search_pro returns ranked passages" in rendered
    assert "platform.kimi.ai" in rendered
    evidence = kimi_web_search.evidence_from_results(pro)
    assert "time_window" in evidence[pro[0]["url"]]


def test_empty_or_invalid_payloads_are_dropped():
    assert kimi_web_search.normalize_search_results({"search_results": []}) == []
    assert kimi_web_search.normalize_search_results({"search_results": [{"title": "x"}]}) == []
    assert kimi_web_search.format_results_for_model([]) == "По запросу ничего не найдено."


def test_search_web_uses_our_metasearch(monkeypatch):
    calls = []

    async def fake_server(query, **kwargs):
        calls.append(query)
        return {'results': kimi_web_search.normalize_search_results(SAMPLE_BASIC), 'status': 'ok'}

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Hosted search must not run")

    monkeypatch.setattr('app.services.server_search.server_search', fake_server)
    monkeypatch.setattr(search_engine, "_search_kimi_sources", forbidden)
    monkeypatch.setattr(search_engine, "_search_openai_sources", forbidden)
    sources = asyncio.run(search_engine.search_web("Kimi web search API REST"))
    assert len(sources) == 2
    assert calls == ["Kimi web search API REST"]


def test_blocked_page_does_not_call_kimi_fetch(monkeypatch):
    async def fail_local(url):
        return url, "[Ошибка: сайт заблокировал доступ (HTTP 403).]"

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Kimi fetch must not run")

    monkeypatch.setattr(web_scraper, "_fetch_url_content_local", fail_local)
    monkeypatch.setattr(kimi_web_search, "kimi_fetch", forbidden)

    url, text = asyncio.run(web_scraper.fetch_url_content("https://example.com/blocked"))
    assert "403" in text
    assert url == "https://example.com/blocked"


def test_kimi_marketplace_browse_uses_shared_reader_before_external_fetch(monkeypatch):
    calls=[]
    async def shared(url, **kwargs):
        calls.append(url)
        return url, 'Домашняя карточка. Цена 1520 рублей. Доставка завтра.'
    async def forbidden(*args, **kwargs):
        raise AssertionError('External Kimi fetch must not precede the shared marketplace reader')
    monkeypatch.setattr(web_scraper,'fetch_url_content',shared)
    monkeypatch.setattr(kimi_web_search,'kimi_fetch',forbidden)
    for url in ['https://www.ozon.ru/product/test-123/', 'https://www.wildberries.ru/catalog/123/detail.aspx', 'https://www.chipdip.ru/product/test']:
        content,sources=asyncio.run(kimi_client._execute_kimi_tool('browse_page',{'url':url}))
        assert 'Домашняя карточка' in content and sources[0]['summary']==url
    assert len(calls)==3


def test_kimi_block_page_is_rejected_and_uses_shared_fallback(monkeypatch):
    async def blocked(url, **kwargs):
        return {'url':url,'markdown':'Похоже, нет\u00a0соединения. Выключите VPN.'}
    async def shared(url, **kwargs):
        return url,'Нормальная страница через сервер'
    monkeypatch.setattr(kimi_web_search,'kimi_fetch',blocked)
    monkeypatch.setattr(web_scraper,'fetch_url_content',shared)
    content,_=asyncio.run(kimi_client._execute_kimi_tool('browse_page',{'url':'https://example.com/card'}))
    assert 'Нормальная страница' in content and 'Выключите VPN' not in content
    assert asyncio.run(web_scraper._recover_with_kimi_fetch('https://example.com/card'))==''


def test_reply_cleanup_preserves_product_listing_links():
    url='https://www.ozon.ru/product/g435-123/?seller=456'
    body=f'Вот объявления:\n- [Logitech G435]({url})\n- [JBL](https://www.ozon.ru/product/jbl-123/)'
    assert kimi_client.strip_source_links(body)==body
    assert kimi_client.strip_source_links('Карточка: '+url)=='Карточка: '+url
    assert kimi_client.strip_source_links(body+'\n\nИсточники\n- https://example.com/source')==body


def test_grounded_context_uses_our_search_and_skips_scrape(monkeypatch):
    async def fake_search_web(query, max_results=14):
        return [{"title": "Web Search Pro docs", "url": "https://platform.kimi.ai/docs", "snippet": "ranked passages"}]

    async def fake_fetch(url):
        raise AssertionError("ordinary search must not scrape")

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("Kimi search must not run")

    monkeypatch.setattr(search_engine, "search_web", fake_search_web)
    monkeypatch.setattr(search_engine, "fetch_url_content", fake_fetch)
    monkeypatch.setattr(search_engine, "_search_kimi_pro", forbidden)
    context, ui = asyncio.run(
        search_engine.build_grounded_web_context("our search", max_results=5, pages_to_read=3)
    )
    assert "ranked passages" in context
    assert ui[0]["query"] == "Web Search Pro docs"


def test_kimi_tool_loop_reads_our_search_results(monkeypatch):
    async def fake_pro(query, **kwargs):
        assert query == "Kimi K3 pricing official"
        return kimi_web_search.normalize_search_results(SAMPLE_PRO)

    monkeypatch.setattr(kimi_web_search, "kimi_search_pro", fake_pro)

    content, sources = asyncio.run(
        kimi_client._execute_kimi_tool("web_search", {"query": "Kimi K3 pricing official"})
    )
    assert "ranked passages" in content
    assert sources[0]["summary"].startswith("https://")


def test_kimi_chat_uses_function_tools_not_builtin():
    assert kimi_client.WEB_SEARCH_TOOL_KIMI["type"] == "function"
    assert kimi_client.WEB_SEARCH_TOOL_KIMI["function"]["name"] == "web_search"
    names = {tool["function"]["name"] for tool in kimi_client.KIMI_SEARCH_TOOLS}
    assert names == {"web_search", "browse_page", "browse_visual"}


def test_kimi_chat_collects_rest_sources(monkeypatch):
    tool_call = SimpleNamespace(
        id="call_1",
        type="function",
        function=SimpleNamespace(
            name="web_search",
            arguments='{"query": "Kimi web search API"}',
        ),
    )
    first = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="",
                    tool_calls=[tool_call],
                )
            )
        ],
    )
    second = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=30),
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="Проверенный результат поиска. " * 8 + "\n[1] Docs — https://platform.kimi.ai/docs/api/tools-search-pro",
                    tool_calls=None,
                )
            )
        ],
    )
    calls = {"n": 0}

    class FakeCompletions:
        async def create(self, **kwargs):
            assert kwargs["tools"] == kimi_client.KIMI_SEARCH_TOOLS
            calls["n"] += 1
            return first if calls["n"] == 1 else second

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    async def fake_pro(query, **kwargs):
        return kimi_web_search.normalize_search_results(SAMPLE_PRO)

    monkeypatch.setattr(kimi_client, "client", FakeClient())
    monkeypatch.setattr(kimi_client, "KIMI_API_KEY", "test-key")
    monkeypatch.setattr(kimi_web_search, "kimi_search_pro", fake_pro)

    answer, _files, _thinking, sources = asyncio.run(
        kimi_client.get_kimi_chat_response([{"role": "user", "content": "что нового в kimi search"}])
    )
    assert "Проверенный результат" in answer
    assert any("platform.kimi.ai" in (item.get("summary") or "") for item in sources)
