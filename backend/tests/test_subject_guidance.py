import pytest
from app.config import get_settings  # noqa: F401
from app.services.subject_guidance import subject_for_query, subject_note, needs_subject_reasoning
from routing import best_route, route_for_turn


@pytest.mark.parametrize('text,domain', [
    ('Почему спорят о причинах падения Римской империи?', 'history'),
    ('Разбери фрагмент по философии и две интерпретации', 'humanities'),
    ('Рассчитай прогиб балки при силе 200 Н', 'engineering'),
    ('Резистор 220 Ом подключили к 12 В. Найди ток и мощность', 'engineering'),
    ('Учебная стационарная тепловая модель: 20 Вт', 'engineering'),
    ('Тепловые сопротивления переход–корпус, 0,5 K/Вт', 'engineering'),
    ('Дай простой рецепт омлета', None),
    ('Переведи: Наполеон и Бородинское сражение', None),
    ('Сегодня у меня нервное напряжение', None),
])
def test_guidance_follows_the_subject_not_a_single_generic_word(text, domain):
    assert subject_for_query(text) == domain


@pytest.mark.parametrize('text', [
    'Почему спорят о причинах падения Римской империи?',
    'Разбери фрагмент по философии и две интерпретации',
    'Рассчитай прогиб балки при силе 200 Н',
    'Резистор 220 Ом подключили к 12 В. Найди ток и мощность',
    'Учебная стационарная тепловая модель: 20 Вт',
])
def test_precision_route_is_strong_even_when_the_prompt_is_short(text):
    assert needs_subject_reasoning(text)
    assert best_route(text, 'none', True, True) == ('gpt-6-sol', True)
    assert best_route(text, 'none', True, False) == ('deepseek-v4-pro', True)
    assert best_route(text, 'none', False, False) == ('gpt-6-sol', True)


def test_simple_definitions_and_unrelated_followups_keep_the_economy_route():
    assert best_route('Что такое историография?', 'none', True, True) == ('deepseek-v4-flash', False)
    assert best_route('Что такое резистор?', 'none', True, True) == ('deepseek-v4-flash', False)
    assert best_route('Переведи: Рассчитай прогиб балки', 'none', True, True) == ('deepseek-v4-flash', False)
    assert route_for_turn('А почему?', 'Рассчитай прогиб балки', True, True) == ('gpt-6-sol', True)
    assert route_for_turn('Привет', 'Рассчитай прогиб балки', True, True) == ('deepseek-v4-flash', False)


def test_domain_contracts_do_not_claim_certification_or_invented_sources():
    assert 'Не сочиняй дословные цитаты' in subject_note('Почему спорят историки?')
    assert 'не подтверждает безопасность' in subject_note('Рассчитай прогиб балки')
    assert 'интерпретации' in subject_note('Объясни философию')
    assert subject_note('Привет') == ''


@pytest.mark.parametrize('text', [
    'Почему этот код вызывает ошибку?',
    'Разбери SQL запрос и объясни причину ошибки',
    'Сравни реализации на Python',
])
def test_code_analysis_gets_subject_contract_and_strong_route(text):
    assert subject_for_query(text) == 'code'
    assert needs_subject_reasoning(text)
    assert best_route(text, 'none', True, True) == ('gpt-6-sol', True)
    assert 'не запускалось' in subject_note(text)


def test_translation_of_code_topic_does_not_activate_code_analysis():
    assert subject_note('Переведи: Python код вызывает ошибку') == ''


def test_code_definition_stays_on_economy_route():
    assert best_route('Что такое Python?', 'none', True, True) == ('deepseek-v4-flash', False)


def test_long_translation_is_not_upgraded_by_source_length_or_keywords():
    text = 'Переведи на английский: ' + ('Архитектура системы и безопасность. ' * 40)
    assert best_route(text, 'none', True, True) == ('deepseek-v4-flash', False)
    assert best_route(text, 'high', True, True)[0] == 'gpt-6-sol'

def test_clock_diagnostics_are_grounded_in_target_and_hardware():
    for prompt in ('Процессор STM32F1xx последовательность настройки тактирования',
                   'Не запускается PLL, не меняется PLLRDY'):
        note = subject_note(prompt)
        assert 'startup/SystemInit' in note
        assert 'PLL/2' in note
        assert 'Отделяй сборку от подтверждения запуска' in note
    assert 'startup/SystemInit' not in subject_note('Объясни сортировку пузырьком')
