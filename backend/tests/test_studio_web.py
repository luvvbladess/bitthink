"""Exercise actual Studio -> Responses tools -> grounded artifact -> source UI."""
import asyncio
import json
from types import SimpleNamespace as NS

import pytest
from app.config import get_settings  # noqa: F401
from app.services.run_protocol import current_run, RunRecord
import studio_router as sr
import openai_client as oc
from studio.research import compose_with_web, needs_current_web, STUDIO_TOOLS


@pytest.mark.parametrize("text", [
    "Слайды про актуальные тарифы", "Обнови статистику рынка",
    "Найди в интернете данные для презентации", "Инфографика: информация за 2026 год",
])
def test_volatile_briefs_require_a_search(text):
    assert needs_current_web(text)


@pytest.mark.parametrize("text", [
    "Сделай шапку темнее", "Нарисуй кота", "Перенеси готовое ТЗ в слайды",
    "Актуальные тарифы из ТЗ, без интернета",
])
def test_cosmetic_and_offline_jobs_do_not_require_search(text):
    assert not needs_current_web(text)


class Stream:
    def __init__(self, output):
        self.output = output

    def __aiter__(self):
        return self.events()

    async def events(self):
        yield NS(type="response.completed", response=NS(output=self.output, usage=None, status="completed"))


@pytest.mark.parametrize("previous", ["", "<!doctype html><html><head><title>Old</title></head><body>старый макет</body></html>"])
def test_create_and_edit_really_search_read_and_return_sources(monkeypatch, previous):
    import search_engine
    import computer_tools
    import studio.html_canvas as hc
    import director_router

    requests, queries, reads = [], [], []
    html = '<!doctype html><html><head><title>Тариф</title></head><body><p>Стоимость 150 ₽ <a href="https://example.org/tariff">Источник</a></p></body></html>'
    outputs = [
        [NS(type="function_call", name="web_search", arguments='{"query":"актуальный тариф"}', call_id="c1", id="c1")],
        [NS(type="function_call", name="browse_page", arguments='{"url":"https://example.org/tariff"}', call_id="c2", id="c2")],
        [NS(type="message", content=[NS(type="output_text", text=html, annotations=[])])],
    ]

    async def create(**request):
        requests.append(request)
        return Stream(outputs.pop(0))

    async def search(query, max_results=14):
        queries.append(query)
        rows = [{"title": "Тариф", "url": "https://example.org/tariff", "snippet": "предыдущая цена 100 ₽"}]
        current_run.get().observe_search(rows, "2026-10-11T12:00:00Z")
        return rows

    async def report(query, sources=None, **kwargs):
        return "Поисковая выдача: предыдущая цена 100 ₽; проверь страницу."

    async def browse(url, query=""):
        reads.append(url)
        return "URL: " + url + "\n\nОфициальный тариф обновлён: стоимость 150 ₽. Условия действуют с 11 октября 2026 года."

    monkeypatch.setattr(oc, "client", NS(responses=NS(create=create)))
    monkeypatch.setattr(search_engine, "search_web", search)
    monkeypatch.setattr(search_engine, "smart_web_search", report)
    monkeypatch.setattr(computer_tools, "_browse_public", browse)
    monkeypatch.setattr(hc, "load_previous_html", lambda uid: previous)
    monkeypatch.setattr(sr, "_needs_clarify", lambda *a, **k: False)
    monkeypatch.setattr(director_router, "_extract_document_context", lambda messages: "")
    monkeypatch.setattr(director_router, "_format_chat_history", lambda messages: "")
    result = asyncio.run(sr.get_studio_response([], "Обнови лендинг: актуальные тарифы", 1, None))
    assert queries == ["актуальный тариф"] and reads == ["https://example.org/tariff"]
    assert requests[0]["tool_choice"] == {"type": "function", "name": "web_search"}
    names = {t.get("name", t["type"]) for t in requests[0]["tools"]}
    assert {"web_search", "browse_page"} <= names <= STUDIO_TOOLS
    assert "workspace_run" not in names and "visualize_data" not in names and "save_skill" not in names
    assert "150 ₽" in result[1][0]["bytes"].decode()
    assert result[3][0]["summary"].startswith("https://example.org/tariff\n")
    assert result[3][0]["evidence_state"] == "read"
    assert current_run.get() is None
    if previous:
        assert "старый макет" in json.dumps(requests[0]["input"], ensure_ascii=False)


def test_pptx_compose_and_pure_edit_have_tools_without_forced_search(monkeypatch):
    calls = []

    async def fake_chat(messages, **kwargs):
        calls.append((messages, kwargs))
        return '{"kind":"deck","title":"Тариф","slides":[]}', [], "", [{"query":"Тариф", "summary":"https://example.org/tariff\nданные"}]

    monkeypatch.setattr(oc, "get_chat_response", fake_chat)
    sources = []
    asyncio.run(sr._compose_spec("Презентация про актуальный тариф", kind="deck", theme_id="noir", document_context="", history_text="", user_id=1, source_items=sources))
    assert calls[0][1]["force_web_search"] and calls[0][1]["allowed_tools"] == STUDIO_TOOLS
    assert sources[0]["summary"].startswith("https://example.org/")
    asyncio.run(compose_with_web([], user_text="Шапку темнее", user_id=1, model="gpt-6-sol", effort="low"))
    assert calls[-1][1]["use_tools"] and not calls[-1][1]["force_web_search"]
    assert not {"web_search", "server_search", "browse_page"} & calls[-1][1]["allowed_tools"]
    asyncio.run(compose_with_web([], user_text="Актуальные тарифы без интернета", user_id=1, model="gpt-6-sol", effort="low"))
    assert not calls[-1][1]["force_web_search"]
    assert not {"web_search", "server_search", "browse_page"} & calls[-1][1]["allowed_tools"]


def test_failed_read_and_empty_search_are_not_claimed_as_verified(monkeypatch):
    async def fake_run(*args, **kwargs):
        current_run.get().observe_page("URL: https://example.org/tariff\n\n[Сайт защищён от автоматического чтения]")
        return "Готово.", [{"filename":"x.html"}], "", []

    monkeypatch.setattr(sr, "_run_studio", fake_run)
    result = asyncio.run(sr.get_studio_response([], "Актуальные цены", 1, None))
    assert result[3][0]["evidence_state"] == "failed"
    assert "подтвердить не удалось" in result[0]
    assert current_run.get() is None


def test_factual_image_gets_research_but_a_cat_does_not(monkeypatch):
    from app.billing import quota

    research_calls, image_prompts = [], []

    async def fake_chat(messages, **kwargs):
        research_calls.append(kwargs)
        current_run.get().observe_search(
            [{"title":"Тариф", "url":"https://example.org/tariff", "snippet":"150 ₽"}],
            "2026-10-11T12:00:00Z",
        )
        return "Тариф 150 ₽: https://example.org/tariff", [], "", []

    async def generate(prompt, **kwargs):
        image_prompts.append(prompt)
        return "data:image/png;base64,iVBORw0KGgo=", None

    monkeypatch.setattr(oc, "get_chat_response", fake_chat)
    monkeypatch.setattr(oc, "generate_image", generate)
    monkeypatch.setattr(quota, "assert_can_generate_image", lambda uid: None)
    monkeypatch.setattr(quota, "debit_images", lambda uid, count: None)
    monkeypatch.setattr(sr, "_image_quality", lambda uid: "low")

    async def run():
        token = current_run.set(RunRecord())
        try:
            researched = await sr._run_image_studio([], "Нарисуй плакат про актуальные тарифы", 1, None)
            cat = await sr._run_image_studio([], "Нарисуй кота", 1, None)
            return researched, cat
        finally:
            current_run.reset(token)

    researched, cat = asyncio.run(run())
    assert len(research_calls) == 1 and research_calls[0]["force_web_search"]
    assert "150 ₽" in image_prompts[0] and image_prompts[1] == "Нарисуй кота"
    assert researched[1][0]["canvas"] and cat[1][0]["canvas"]


def test_explicit_url_is_read_even_when_the_model_does_not_browse(monkeypatch):
    import computer_tools
    captured, reads = [], []

    async def browse(url, query=""):
        reads.append(url)
        return "URL: " + url + "\n\nПервоисточник: актуальная цена 150 ₽, действует с сегодняшнего дня."

    async def fake_chat(messages, **kwargs):
        captured.append((messages, kwargs))
        return '<html><head><title>Тариф</title></head><body>150 ₽</body></html>', [], "", []

    monkeypatch.setattr(computer_tools, "_browse_public", browse)
    monkeypatch.setattr(oc, "get_chat_response", fake_chat)

    async def run():
        token = current_run.set(RunRecord())
        try:
            await sr._compose_html(
                "Лендинг: актуальные тарифы https://example.org/tariff.",
                kind="landing",document_context="",history_text="",user_id=1,
                direction={},
            )
            assert current_run.get().sources[0]["status"] == "read"
        finally:
            current_run.reset(token)

    asyncio.run(run())
    assert reads == ["https://example.org/tariff"]
    assert "150 ₽" in json.dumps(captured[0][0],ensure_ascii=False)
    assert not captured[0][1]["force_web_search"]  # already has the supplied primary page
