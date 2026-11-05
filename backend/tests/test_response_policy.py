import json
import pytest
from app.services.response_policy import compact_answer_kind, compact_model
from app.services.answer_format import normalize_answer_format


@pytest.mark.parametrize('task', [
    'Разбери вымышленный литературный отрывок: «Он вернул ключ».',
    'Сравни философию Канта и утилитаризм',
    'Объясни ошибку в коде: def f(items=[]): return items',
    'Верни только JSON: Анна, телефон не указан',
    'Переведи на английский: встреча завтра',
])
def test_bounded_answers_need_one_writer(task):
    assert compact_answer_kind(task) == 'text'


@pytest.mark.parametrize('task', [
    'Отправь письмо клиенту', 'Сравни прикреплённые PDF',
    'Исправь код в проекте и запусти тесты', 'Объясни, как удалить файлы на сервере',
    'Рассчитай прогиб балки', 'Проверь безопасность JWT',
    'Подбери ресторан в Москве', 'Найди лучший ноутбук в бюджете 50000',
    'Объясни философию и открой Википедию',
    'Объясни функцию и проверь результат инструментом',
    'Объясни мои заметки',
    'Сравни три отчета',
    'Сравни три сайта',
])
def test_shortcuts_do_not_swallow_actions_or_specialized_work(task):
    assert compact_answer_kind(task) == ''


def test_source_lookup_uses_a_single_agent_but_keeps_web_tools():
    assert compact_answer_kind('Найди текущую стабильную версию Python на официальном сайте', web_required=True) == 'web'
    assert compact_answer_kind('По официальным источникам объясни asyncio.to_thread', web_required=True) == 'web'
    assert compact_answer_kind('Найди текущую стабильную версию Python на официальном сайте') == 'web'
    assert compact_answer_kind('По официальной документации Python объясни copy.copy и copy.deepcopy') == 'web'


def test_url_inside_supplied_code_does_not_require_research():
    text = 'Почему этот Python код блокирует event loop? async def fetch():\n    return requests.get("https://example.com").text'
    assert compact_answer_kind(text, web_required=True) == 'text'


def test_budget_saved_from_tools_can_keep_strong_reasoning_within_tier():
    task = 'Сравни философию Канта и утилитаризм'
    assert compact_model(task, ['gpt-6-sol', 'gpt-6-luna']) == 'gpt-6-sol'
    assert compact_model(task, ['gpt-6-luna']) == 'gpt-6-luna'
    assert compact_model('Что такое Python?', ['gpt-6-sol', 'gpt-6-luna']) == 'gpt-6-luna'
    assert compact_model(task, ['claude-haiku-5.5', 'gpt-6-luna']) == 'gpt-6-luna'


def test_json_fence_is_removed_only_for_explicit_json_output():
    source = '```json\n{"value":"<div>—</div>","phone":null}\n```'
    result = normalize_answer_format(source, 'Верни только JSON: данные')
    assert json.loads(result) == {'value':'<div>—</div>', 'phone':None}
    assert normalize_answer_format(source, 'Объясни JSON на примере') == source
    assert normalize_answer_format(source, 'Переведи: верни только JSON') == source


@pytest.mark.parametrize('answer', ['```json\n{broken}\n```', 'Пример:\n```json\n{}\n```', '```json\n{"value":NaN}\n```'])
def test_invalid_or_mixed_outputs_are_not_silently_rewritten(answer):
    assert normalize_answer_format(answer, 'Верни только JSON') == answer


def test_structured_string_values_survive_presentation_cleanup():
    from handlers.core import sanitize_response_text
    text = '{"code":"<div>—</div>","operator":"a << 2"}'
    assert sanitize_response_text(text) == text
    code = '```python\nvalue = "<div>—</div>"\n```'
    assert sanitize_response_text(code) == code


def test_compaction_preserves_custom_rules_memory_history_and_safety():
    from config import SYSTEM_PROMPT
    from app.services.search_budget import SEARCH_PLAN
    from app.services.response_policy import compact_messages
    custom = {'role':'system', 'content':'Пользователь предпочитает английский, только три пункта.'}
    history = {'role':'assistant', 'content':'Previous answer'}
    original = [{'role':'system', 'content':SYSTEM_PROMPT}, custom, history,
                {'role':'system', 'content':SEARCH_PLAN}, {'role':'user', 'content':'Что такое Python?'}]
    result = compact_messages(original)
    assert custom in result and history in result
    assert len(result[0]['content']) < len(SYSTEM_PROMPT) / 2
    assert 'Не помогай создавать оружие' in result[0]['content']
    assert 'самоповреждении' in result[0]['content']
    assert not any(m.get('content') == SEARCH_PLAN for m in result)
    assert original[0]['content'] == SYSTEM_PROMPT
    assert custom == compact_messages([custom])[0]
