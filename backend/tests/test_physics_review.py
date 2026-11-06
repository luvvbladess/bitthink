import asyncio
from unittest.mock import AsyncMock
import pytest
from app.services.physics_review import advanced_physics, specification
from app.services.orchestrator_budget import RunBudget, current_budget


@pytest.mark.parametrize('task', ['Сделай сайт: красивую симуляцию чёрной дыры с физикой и частицами',
    'Симуляция гравитационного линзирования', 'Разработай модель гидродинамики жидкости',
    'Create a black hole simulation', 'Сделай игру с крутой физикой', 'В симуляции сделай физику крутую'])
def test_complex_physics_is_recognized(task):
    assert advanced_physics(task)


@pytest.mark.parametrize('task', ['Красивый фон с частицами для магазина', 'Поменяй цвет кнопки в симуляции чёрной дыры',
    'Анимация черной дыры без физики', 'Переведи: black hole simulation',
    'Доработай проект.\nИсходные требования:\nСимуляция чёрной дыры.\nНовые правки пользователя:\nПоменяй цвет заголовка'])
def test_decorative_or_routine_work_does_not_get_a_premium_review(task):
    assert not advanced_physics(task)


@pytest.mark.parametrize('allowed,remaining,expected', [(['gpt-6-astra','gpt-6-sol'],.6,'gpt-6-astra'),
    (['gpt-6-sol'],.6,'gpt-6-sol'), (['gpt-6-astra','gpt-6-sol'],.1,'gpt-6-sol'),
    (['gpt-6-luna'],.6,None), (['gpt-6-astra','gpt-6-sol'],.02,None)])
def test_review_respects_tier_budget_and_output_limit(monkeypatch, allowed, remaining, expected):
    response = AsyncMock(return_value=('Формулы и проверяемые ограничения.',[], '', []))
    monkeypatch.setattr('openai_client.get_chat_response', response)
    token = current_budget.set(RunBudget(remaining))
    try:
        result = asyncio.run(specification('Симуляция чёрной дыры',1,allowed))
    finally:
        current_budget.reset(token)
    if expected is None:
        assert result is None and not response.called
    else:
        assert result['model'] == expected and result['physics_spec']
        assert response.call_count == 1
        assert response.call_args.kwargs['use_tools'] is False
        assert response.call_args.kwargs['use_skills'] is False
        assert response.call_args.kwargs['output_token_limit'] == 2400


def test_provider_failure_never_discards_the_product(monkeypatch):
    monkeypatch.setattr('openai_client.get_chat_response', AsyncMock(side_effect=RuntimeError('unavailable')))
    assert asyncio.run(specification('Симуляция чёрной дыры',1,['gpt-6-sol'])) is None


@pytest.mark.parametrize('allowed,expected', [(['gpt-6-luna','gpt-6-sol'],'gpt-6-sol'), (['gpt-6-luna'],'gpt-6-luna')])
def test_physics_builder_is_strong_within_the_available_tier(monkeypatch, allowed, expected):
    import director_router as dr
    monkeypatch.setattr(dr, '_employee_models', lambda uid: allowed)
    plan = dr._clamp_employee_plan({'new_employees':[{'role':'Разработка','task':'Реализуй модель',
        'product_phase':'build','model':'gpt-6-luna'}]},1,'Сделай сайт: симуляцию чёрной дыры с физикой')
    assert plan['new_employees'][0]['model'] == expected
