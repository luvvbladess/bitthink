import asyncio
import pytest
from app.services.answer_tools import computation_query, python_reference_urls, _read_references


def test_compute_uses_supplied_quantities_and_followup_only():
    assert computation_query('Вычисли 1/17 + 1/19 + 1/23.')
    history = [{'role':'user', 'content':'Посчитай 100000 с ростом 0.75% за 23 месяца'}]
    assert computation_query('Пересчитай за 24 месяца', history)
    assert not computation_query('Сколько сегодня стоит 1 доллар и 1 евро?')
    assert not computation_query('Переведи: посчитай 3 + 4')
    assert not computation_query('Рассчитай дозу лекарства 20 мг ребенку 3 лет')
    assert not computation_query('Сколько стоят iPhone 16 и iPhone 17?')
    assert not computation_query('Вычисли результат Python: a=[3,4]; print(a[1])')


def test_reference_version_and_followup_do_not_mix_versions():
    assert python_reference_urls('По официальной документации Python 3.12 объясни asyncio.wait_for') == ['https://docs.python.org/3.12/library/asyncio-task.html']
    history = [{'role':'user','content':'По официальной документации Python 3.12 объясни functools.cached_property'}]
    assert python_reference_urls('А по официальной документации Python 3.11?', history) == ['https://docs.python.org/3.11/library/functools.html','https://docs.python.org/3.12/library/functools.html']
    assert not python_reference_urls('Без интернета объясни Python functools.cached_property')
    assert not python_reference_urls('По официальной документации Python 3.12 исправь файл проекта asyncio.py')
    assert python_reference_urls('А что говорит официальная документация об этом?', history) == ['https://docs.python.org/3.12/library/functools.html']
    assert not python_reference_urls('По официальной документации Python 3.12 сравни asyncio.gather, itertools.groupby и functools.cache')
    assert not python_reference_urls('По официальной документации Python 3.10, 3.11 и 3.12 сравни functools.cached_property')


def test_reference_search_snippet_is_not_treated_as_read(monkeypatch):
    import computer_tools
    from app.services.run_protocol import RunRecord
    url = 'https://docs.python.org/3/library/functools.html'
    record = RunRecord()
    async def failed(*args):
        return 'URL: ' + url + '\nSearch fallback only'
    monkeypatch.setattr(computer_tools, 'run_computer_tool', failed)
    assert asyncio.run(_read_references([url], 'question', 1, record)) is None


def test_calculation_route_has_only_readonly_tool_and_resets_billing(monkeypatch):
    import openai_client
    from app.services.answer_tools import maybe_tool_answer
    from app.billing.quota import billing_pool
    from app.services.run_protocol import current_run
    before = current_run.get()
    old_pool = billing_pool.get()
    async def fail(messages, **kwargs):
        assert kwargs['allowed_tools'] == frozenset({'calculate'})
        assert kwargs['required_first_tool'] == 'calculate'
        assert billing_pool.get() == 'computer'
        raise RuntimeError('simulated API failure')
    monkeypatch.setattr(openai_client, 'get_chat_response', fail)
    with pytest.raises(RuntimeError):
        asyncio.run(maybe_tool_answer([{'role':'user','content':'Вычисли 3+4'}], 'Вычисли 3+4', 1, {'gpt-6-luna'}, pool='computer'))
    assert billing_pool.get() == old_pool
    assert current_run.get() is before
