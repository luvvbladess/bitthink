import asyncio
from types import SimpleNamespace as NS

import pytest

from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path
import openai_client as oc


def _message(text):
    return NS(type="message", content=[NS(type="output_text", text=text, annotations=[])])


def _response(output, status="completed", **extra):
    return NS(output=output, usage=None, status=status, **extra)


class _Stream:
    def __init__(self, events):
        self._events = events

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for event in self._events:
            yield event


def _run(monkeypatch, scripted, text="привет", **kwargs):
    """Run get_chat_response against a scripted fake of the Responses stream; return (result, requests)."""
    requests = []

    async def create(**request):
        requests.append(request)
        return _Stream(scripted.pop(0))

    monkeypatch.setattr(oc, "client", NS(responses=NS(create=create)))
    result = asyncio.run(
        oc.get_chat_response(
            [{"role": "user", "content": text}], model="gpt-6-luna", use_tools=True, force_web_search=True, **kwargs
        )
    )
    return result, requests


def _completed(*output):
    return [NS(type="response.completed", response=_response(list(output)))]


def test_parallel_read_results_keep_call_ids_in_responses_loop(monkeypatch):
    import computer_tools
    active = peak = 0
    requests = []
    scripted = [_completed(*[NS(type='function_call', name='browse_page', arguments='{"url":"https://example.com/%d"}' % i,
                                  call_id=f'read-{i}', id=f'read-{i}') for i in range(3)]), _completed(_message('Сравнение готово'))]
    async def create(**request):
        requests.append(request)
        return _Stream(scripted.pop(0))
    async def read(name, args, uid):
        nonlocal active, peak
        active += 1; peak = max(peak, active)
        await asyncio.sleep(.02)
        active -= 1
        return 'URL: ' + args['url'] + '\n\nПрочитанные параметры'
    monkeypatch.setattr(oc, 'client', NS(responses=NS(create=create)))
    monkeypatch.setattr(computer_tools, 'run_computer_tool', read)
    result = asyncio.run(oc.get_chat_response([{'role':'user','content':'Сравни три страницы'}],
                                            model='gpt-6-luna', use_tools=True, chat_tools=True))
    assert peak == 3 and result[0] == 'Сравнение готово'
    outputs = [item for item in requests[1]['input'] if isinstance(item, dict) and item.get('type') == 'function_call_output']
    assert [item['call_id'] for item in outputs] == ['read-0', 'read-1', 'read-2']
    assert all(f'https://example.com/{i}' in item['output'] for i, item in enumerate(outputs))


@pytest.mark.parametrize("text", ["привет", "Привет!", "hello", "спасибо", "пока", "привет, друг"])
def test_a_greeting_is_not_a_search_request(text):
    assert oc._is_smalltalk(text)


@pytest.mark.parametrize("text", ["привет, какой курс доллара?", "курс евро", "что нового в мире", "Привет! Найди мне отель", ""])
def test_real_questions_are_not_smalltalk(text):
    assert not oc._is_smalltalk(text)


def test_forced_search_demands_the_web_search_itself_on_a_real_question(monkeypatch):
    result, requests = _run(monkeypatch, [_completed(_message("94,3 ₽"))], text="Какой сейчас курс евро?")
    assert requests[0]["tool_choice"] == {"type": "function", "name": "web_search"}
    assert result[0] == "94,3 ₽"


def test_forced_research_can_read_a_page_after_search_without_mutation_tools(monkeypatch):
    import computer_tools
    read = NS(type='function_call', name='browse_page', arguments='{"url":"https://stats.example/hero"}', call_id='read', id='read')
    async def page(name, args, uid):
        assert name == 'browse_page'
        return 'URL: https://stats.example/hero\n\nWin rate 51.5%, ranked, last 7 days'
    monkeypatch.setattr(computer_tools, 'run_computer_tool', page)
    result, requests = _run(monkeypatch, [_completed(read), _completed(_message('51.5%, ranked, 7 days'))], text='Find current hero winrate')
    offered = {t.get('name') for t in requests[0]['tools']}
    assert {'web_search', 'server_search', 'browse_page'} <= offered
    assert not {'ssh_exec', 'workspace_write', 'site_login', 'project_result'} & offered
    assert '51.5%' in result[0]
    assert any('51.5%' in str(item.get('output', '')) for item in requests[1]['input'] if isinstance(item, dict))


def test_a_greeting_in_search_mode_is_just_answered(monkeypatch):
    result, requests = _run(monkeypatch, [_completed(_message("Привет!"))], text="привет")
    assert "tool_choice" not in requests[0]
    assert result[0] == "Привет!"


def test_the_demand_is_made_once_not_on_every_hop(monkeypatch):
    # Hop 1: the model calls a tool. Hop 2 must be free to just answer; with "required" on every hop
    # it called tools again until the API cut the response off, which is the bug being fixed.
    call = NS(type="function_call", name="list_skills", arguments="{}", call_id="c1", id="c1")
    result, requests = _run(
        monkeypatch,
        [_completed(call), _completed(_message("Готово"))],
        text="Какой сейчас курс евро?",
    )
    assert len(requests) == 2
    assert requests[0]["tool_choice"] == {"type": "function", "name": "web_search"}
    assert "tool_choice" not in requests[1]
    assert result[0] == "Готово"


def test_an_answer_cut_short_is_shown_not_discarded(monkeypatch):
    cut = [NS(type="response.incomplete", response=_response(
        [_message("Начало ответа")], status="incomplete", incomplete_details=NS(reason="max_output_tokens"),
    ))]
    result, _ = _run(monkeypatch, [cut], text="Расскажи подробно про курс евро")
    assert result[0] == "Начало ответа"


def test_short_research_reserves_last_hop_for_synthesis(monkeypatch):
    call = NS(type="function_call", name="list_skills", arguments="{}", call_id="c1", id="c1")
    result, requests = _run(
        monkeypatch, [_completed(call), _completed(_message("Готовый ответ по найденным данным"))],
        text="Найди свежие обзоры", max_tool_loops=2,
    )
    assert requests[0]["tool_choice"] == {"type": "function", "name": "web_search"}
    assert requests[1]["tool_choice"] == "none"
    assert result[0] == "Готовый ответ по найденным данным"


def test_the_real_reason_is_shown_when_the_response_fails(monkeypatch):
    failed = [NS(type="response.failed", response=NS(error=NS(message="Rate limit reached for requests")))]
    result, _ = _run(monkeypatch, [failed], text="Какой сейчас курс евро?")
    assert "Rate limit reached" in result[0]
    assert "прервала поток" not in result[0]


def test_function_web_search_reports_one_source_per_link(monkeypatch):
    import search_engine

    async def fake_search(query, max_results=14):
        return [{"title": "ЦБ РФ", "url": "https://cbr.ru/x", "snippet": "курс"}]

    async def fake_smart(query, max_results=14, sources=None):
        assert sources and sources[0]["url"] == "https://cbr.ru/x"
        return "report"

    monkeypatch.setattr(search_engine, "search_web", fake_search)
    monkeypatch.setattr(search_engine, "smart_web_search", fake_smart)
    call = NS(type="function_call", name="web_search", arguments='{"query": "курс"}', call_id="c1", id="c1")
    result, _ = _run(monkeypatch, [_completed(call), _completed(_message("Готово"))], text="Какой курс евро?")
    assert [s["summary"].split("\n")[0] for s in result[3]] == ["https://cbr.ru/x"]
