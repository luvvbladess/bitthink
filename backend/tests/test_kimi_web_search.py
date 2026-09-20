import asyncio
from types import SimpleNamespace

from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path

import kimi_client
import kimi_web_search
import search_engine
import web_scraper


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


def test_search_web_uses_rest_basic_before_openai(monkeypatch):
    calls = []

    async def fake_search(query, **kwargs):
        calls.append(("basic", query, kwargs.get("limit")))
        return kimi_web_search.normalize_search_results(SAMPLE_BASIC)

    async def forbidden_openai(*_args, **_kwargs):
        raise AssertionError("OpenAI fallback must not run when Kimi REST is useful")

    monkeypatch.setattr(kimi_web_search, "kimi_search", fake_search)
    monkeypatch.setattr(search_engine, "_search_openai_sources", forbidden_openai)
    sources = asyncio.run(search_engine.search_web("Kimi web search API REST"))
    assert len(sources) == 2
    assert calls and calls[0][0] == "basic"


def test_scraper_falls_back_to_kimi_fetch(monkeypatch):
    async def fail_local(url):
        return url, "[Ошибка: сайт заблокировал доступ (HTTP 403).]"

    async def fake_fetch(url, **kwargs):
        return {"url": url, "title": "Fetched", "markdown": "# Hello from Kimi Fetch\n\nBody text here."}

    monkeypatch.setattr(web_scraper, "_fetch_url_content_local", fail_local)
    monkeypatch.setattr(kimi_web_search, "kimi_fetch", fake_fetch)

    url, text = asyncio.run(web_scraper.fetch_url_content("https://example.com/blocked"))
    assert "Hello from Kimi Fetch" in text
    assert url == "https://example.com/blocked"


def test_grounded_context_uses_pro_chunks_and_skips_scrape(monkeypatch):
    scraped = []

    async def fake_pro(query, max_results):
        return kimi_web_search.normalize_search_results(SAMPLE_PRO)

    async def fake_fetch(url):
        scraped.append(url)
        return url, "should not scrape"

    monkeypatch.setattr(search_engine, "_search_kimi_pro", fake_pro)
    monkeypatch.setattr(search_engine, "fetch_url_content", fake_fetch)
    context, ui = asyncio.run(
        search_engine.build_grounded_web_context("Kimi search_pro chunks", max_results=5, pages_to_read=3)
    )
    assert "ranked passages" in context
    assert scraped == []
    assert ui[0]["query"] == "Web Search Pro docs"


def test_grounded_context_does_not_pay_for_basic_after_pro(monkeypatch):
    search_web_calls = []

    async def fake_pro(query, max_results):
        return kimi_web_search.normalize_search_results(SAMPLE_PRO)[:1]

    async def fake_search_web(query, max_results=14):
        search_web_calls.append(query)
        return [{"title": "should not run", "url": "https://example.com", "snippet": ""}]

    async def fake_fetch(url):
        return url, "should not scrape"

    monkeypatch.setattr(search_engine, "_search_kimi_pro", fake_pro)
    monkeypatch.setattr(search_engine, "search_web", fake_search_web)
    monkeypatch.setattr(search_engine, "fetch_url_content", fake_fetch)
    context, ui = asyncio.run(
        search_engine.build_grounded_web_context("zzz", max_results=5, pages_to_read=3)
    )
    assert search_web_calls == []
    assert "ranked passages" in context
    assert len(ui) == 1
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
    assert names == {"web_search", "browse_page"}


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
