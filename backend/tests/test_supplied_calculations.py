import pytest
from app.services.source_quality import guard_current_numbers
from app.services.orchestrator_policy import calculation_task

@pytest.mark.parametrize('query,answer', [
 ('В магазине цену 8000 рублей повысили на 20%, затем снизили на 20%. Какова итоговая цена?', 'Итоговая цена: 7680 рублей, снижение на 4%.'),
 ('Есть 100000 рублей, долг под 40% и вклад под 15%. Дай расчёт за год при неизменных ставках.', 'Долг: 40000 рублей. Вклад: 15000 рублей. Разница: 25000 рублей.'),
 ('Продажи: январь 100, февраль 120, март 90. Рассчитай изменения.', 'Рост: 20%. Падение: 25%. Итог: -10%.'),
])
def test_supplied_calculations_survive_numeric_guard(query, answer):
 assert calculation_task(query)
 assert guard_current_numbers(answer, {}, query=query) == answer
 assert guard_current_numbers(answer, {'https://example.com': 'Unrelated page'}, query=query) == answer

@pytest.mark.parametrize('query', [
 'Найди вклад под 15% и рассчитай доход со 100000 рублей.',
 'Рассчитай стоимость 2 ноутбуков, проверь цены сейчас.',
 'Какова итоговая цена 2 ноутбуков? Найди актуальные предложения.',
])
def test_live_prices_still_require_evidence(query):
 assert not calculation_task(query)
 assert '99999' not in guard_current_numbers('Ноутбук: 99999 рублей.', {}, query=query)
