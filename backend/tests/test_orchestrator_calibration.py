import asyncio
from datetime import datetime, timezone

import pytest
from app.config import get_settings  # noqa: F401
from app.services.orchestrator_policy import bounded_text_task, critical_task
from computer_skills.loader import match_skills
import director_router as dr


@pytest.mark.parametrize('query', [
    'Напиши короткое письмо коллеге: встречу переносим на 16:00. Ничего не отправляй.',
    'Составь сообщение клиенту: заказ задерживается. Только черновик, не отправляй.',
    'Перепиши вежливо: «Вы опять не прислали документы».',
    'Переведи на английский: «Счёт оплатим до 5 ноября».',
    'Переведи на английский, сохрани дату и сумму: «Счёт оплатим до 5 ноября».',
    'Кратко перескажи в двух пунктах: команда выпустила приложение; две ошибки остались.',
    'Извлеки JSON из текста: Анна, anna@example.com, 1450 рублей.',
    'Составь план изучения английского на неделю по 20 минут.',
])
def test_inline_text_does_not_hire_a_team_or_mailbox(query):
    assert bounded_text_task(query)
    assert dr._is_light_task(query, '', False, None)
    assert not {'email', 'documents', 'workspace'} & set(match_skills(query, sandbox=True))


@pytest.mark.parametrize('query', [
    'Переведи прикреплённый PDF на русский',
    'Переведи документ на русский',
    'Напиши письмо и отправь его на anna@example.com',
    'Напиши письмо: встреча завтра. Затем отправь его клиенту.',
    'Составь план миграции базы данных',
    'Составь план изучения уязвимости авторизации',
    'Напиши договор поставки с ограничением ответственности',
    'Перепиши файл app.py: исправь ошибку.',
    'Подготовь презентацию в PPTX',
    'Напиши письмо и найди контакты клиента',
    'Напиши письмо: встреча завтра. Подготовь отдельный PDF.',
])
def test_external_operations_and_expert_work_keep_the_planner(query):
    assert not bounded_text_task(query)


@pytest.mark.parametrize('query', [
    'Докажи, что n² чётно только при чётном n. Без поиска.',
    'Проверь безопасность JWT: подпись не проверяется.',
    'Внезапно перекосило лицо и невнятная речь. Что делать?',
    'Как исправить гонку транзакций в PostgreSQL?',
])
def test_short_expert_question_never_falls_through_to_cheap_direct_answer(query, monkeypatch):
    assert critical_task(query)
    monkeypatch.setattr(dr, '_employee_models', lambda uid: list(dr.MODEL_POOL))
    assert dr._direct_answer_model(1, query) == dr.PLANNER_MODEL
    assert dr._needs_strong_model(query, '', False, None)


def test_inline_shortcut_never_discards_documents_or_images():
    query = 'Напиши письмо коллеге: встреча завтра.'
    assert not dr._is_light_task(query, 'Attached document', False, None)
    assert not dr._is_light_task(query, '', True, None)


def test_mailbox_operation_still_loads_email():
    assert 'email' in match_skills('Найди в Gmail непрочитанные письма от клиента', sandbox=True)


def test_midnight_uses_same_moscow_date_in_planner_and_model(monkeypatch):
    import runtime_context as rc
    class Clock:
        @staticmethod
        def now(tz=None):
            moment = datetime(2026, 10, 31, 22, 30, tzinfo=timezone.utc)
            return moment.astimezone(tz) if tz else moment.replace(tzinfo=None)
    monkeypatch.setattr(rc, 'datetime', Clock)
    assert '01.11.2026' in rc.current_date_note()
    assert '01.11.2026' in dr._current_date_note()


def test_evaluation_scores_wrong_json_and_missing_tools():
    from evals.calibrate import assertions
    row = {'answer':'{"phone":"invented"}', 'tools':[], 'calls':[], 'route':{}}
    errors = assertions({'json_expected':{'phone':None}, 'required_tools_any':['python_run']}, row)
    assert 'json_value' in errors
    assert 'required_tool_missing' in errors


@pytest.mark.parametrize('query', [
    'Товар стоит 18750. Скидки 12% и 5%. Сколько платить? Проверь вычисление инструментом.',
    'Доход 85000, расходы 61100. Посчитай остаток и срок накопления 120000.',
    'Проверь безопасность JWT без интернета.',
    'Составь план изучения английского: 20 минут каждый день.',
    'В договоре написано: «Поставщик меняет цену после оплаты». Какие риски для покупателя?',
])
def test_local_verification_is_not_forced_into_web_only_worker(query):
    assert not dr.needs_research(query, False)


def test_live_fact_keeps_web_research():
    assert dr.needs_research('Какой официальный курс доллара на сегодня?', False)
    assert dr.needs_research('Открой https://python.org/downloads/ и проверь текущую версию', False)


def test_learning_schedule_is_not_a_background_automation():
    assert 'wf_automations' not in match_skills('Составь план изучения английского: 20 минут каждый день.', sandbox=True)
    assert 'wf_automations' in match_skills('Завтра напомни проверить отчёт', sandbox=True, limit=5)


def test_arithmetic_uses_science_not_engineering_normcontrol():
    skills = match_skills('Доход 85000, расходы 61100. Проверь расчёт остатка инструментом.', sandbox=True)
    assert 'science' in skills
    assert 'eng_calc_check' not in skills


def test_direct_model_override_respects_subscription_and_registry(monkeypatch):
    monkeypatch.setattr(dr, '_employee_models', lambda uid: ['gpt-6-luna', 'minimax-m3.1-flash'])
    monkeypatch.setenv('ORCHESTRATOR_DIRECT_MODEL', 'minimax-m3.1-flash')
    assert dr._direct_answer_model(1) == 'minimax-m3.1-flash'
    for invalid in ['unknown-model', dr.OPUS_MODEL]:
        monkeypatch.setenv('ORCHESTRATOR_DIRECT_MODEL', invalid)
        assert dr._direct_answer_model(1) == dr.DIRECT_ANSWER_MODEL


@pytest.mark.parametrize('actions,expected_fallback_calls', [(0, 1), (1, 0)])
def test_direct_provider_fallback_cannot_repeat_completed_tool_actions(monkeypatch, actions, expected_fallback_calls):
    import openai_client
    import openrouter_client
    from app.services.model_result import ModelResult
    monkeypatch.setattr(dr, '_direct_answer_model', lambda *args: 'minimax-m3.1-flash')
    fallbacks = []
    async def router(*args, **kwargs):
        return ModelResult('Provider unavailable', error_kind='provider_error', retryable=True, actions_executed=actions)
    async def fallback(*args, **kwargs):
        fallbacks.append(kwargs['model'])
        return ModelResult('Recovered')
    monkeypatch.setattr(openrouter_client, 'get_openrouter_response', router)
    monkeypatch.setattr(openai_client, 'get_chat_response', fallback)
    result = asyncio.run(dr._answer_directly([{'role':'user','content':'Привет'}], 1))
    assert len(fallbacks) == expected_fallback_calls
    assert result[0] == ('Recovered' if not actions else 'Provider unavailable')


def test_text_revision_inherits_only_previous_draft():
    from app.services.orchestrator_policy import bounded_text_revision
    task = 'Сделай теплее, сохрани все ограничения.'
    assert bounded_text_revision(task, [{'role':'user','content':'Напиши поздравление Марине на вы, до 40 слов.'}])
    assert not bounded_text_revision(task, [{'role':'user','content':'Исправь приложение в проекте'}])
    assert not bounded_text_revision('Сделай теплее и отправь письмо', [{'role':'user','content':'Напиши письмо клиенту'}])
