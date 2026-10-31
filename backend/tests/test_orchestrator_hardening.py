import asyncio
import uuid

import pytest
from app.config import get_settings  # noqa: F401
from app.billing.costs import model_cost_usd, spend_summary, merge_usage
from app.billing.plans import billed_multiplier, computer_models
from app.billing.call_budget import estimate_text_input
from app.services.model_registry import MODELS, experimental_workers
from app.services.orchestrator_budget import RunBudget, RunBudgetExceeded, current_budget, run_budget
from app.services.orchestrator_metrics import model_trace, mark_outcome
from conversations import conversation_manager as manager
import director_router as dr


def test_haiku_day_and_month_cost_are_the_sum_of_requests():
    uid = 720_000_000 + uuid.uuid4().int % 10_000_000
    for _ in range(3):
        manager.track_tokens(uid, dr.HAIKU_MODEL, 40_000, 1000, debit=False)
    day = manager.get_day_usage(uid)
    month = manager.get_month_usage(uid)
    assert day[dr.HAIKU_MODEL]['input'] == 120_000
    assert spend_summary(day)['usd'] == .0135
    assert spend_summary(month)['usd'] == .0135
    assert spend_summary(month)['cost_complete']
    assert model_cost_usd(dr.HAIKU_MODEL, 120_000, 3000) == pytest.approx(.0675)


def test_legacy_aggregate_does_not_invent_one_long_request():
    summary = spend_summary({dr.HAIKU_MODEL: {'input': 120_000, 'output': 3000}})
    assert summary['usd'] == .0135
    assert not summary['cost_complete']


def test_provider_cost_is_preserved_across_daily_merges():
    uid = 730_000_000 + uuid.uuid4().int % 10_000_000
    manager.track_tokens(uid, dr.HAIKU_MODEL, 100, 20, debit=False, actual_usd=.0021)
    manager.track_tokens(uid, dr.HAIKU_MODEL, 100, 20, debit=False, actual_usd=.0031)
    part = manager.get_day_usage(uid)
    assert spend_summary(part)['usd'] == .0052
    assert spend_summary(merge_usage([part, part]))['usd'] == .0104


def test_long_context_pricing_belongs_to_each_model():
    assert billed_multiplier(dr.SONNET_MODEL, 300_000) == 20
    assert billed_multiplier(dr.OPUS_MODEL, 300_000) == 40
    assert billed_multiplier('deepseek-v4-pro', 300_000) == 9
    assert billed_multiplier(dr.HAIKU_MODEL, 100_000) == 1
    assert billed_multiplier(dr.HAIKU_MODEL, 100_001) == 5
    assert model_cost_usd('gpt-6-sol', 300_000, 10_000) == pytest.approx(1.35)
    assert model_cost_usd(dr.SONNET_MODEL, 300_000, 10_000) == pytest.approx(.70)


def test_haiku_cache_write_uses_long_tier_without_double_counting():
    assert model_cost_usd(dr.HAIKU_MODEL, 120_000, 1000, cached_input_tokens=20_000,
        cache_write_tokens=40_000) == pytest.approx(.0585)


def test_claude_image_transport_size_does_not_invent_a_long_text_prompt():
    def request(size):
        return {'model': 'anthropic/claude-haiku-5.5', 'messages': [{'role': 'user', 'content': [
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + 'x' * size}}]}]}
    assert estimate_text_input(request(1_000_000)) == estimate_text_input(request(100))
    assert 5000 < estimate_text_input(request(100)) < 15_000


def test_production_economy_workers_are_enabled_for_paid_orchestrator(monkeypatch):
    monkeypatch.delenv('ORCHESTRATOR_EXPERIMENTAL_MODELS', raising=False)
    assert experimental_workers() == []
    monkeypatch.delenv('ORCHESTRATOR_ECONOMY_WORKERS', raising=False)
    assert 'glm-5.3-flash' in computer_models('creator')
    assert 'minimax-m3.1-flash' in computer_models('creator')
    assert 'glm-5.3-flash' not in computer_models('free')
    monkeypatch.setenv('ORCHESTRATOR_ECONOMY_WORKERS', '')
    assert 'glm-5.3-flash' not in computer_models('creator')


def test_sonnet_is_preserved_for_a_strong_product_stage(monkeypatch):
    monkeypatch.setattr(dr, '_employee_models', lambda uid: list(dr.MODEL_POOL))
    monkeypatch.setattr('config.OPENROUTER_API_KEY', 'test-key')
    plan = dr._clamp_employee_plan({'new_employees': [{'role': 'Сборка', 'task': 'Реализуй приложение',
        'model': dr.SONNET_MODEL, 'product_phase': 'build'}]}, 1, 'Создай приложение с авторизацией')
    assert plan['new_employees'][0]['model'] == dr.SONNET_MODEL


def test_advanced_synthesis_is_not_downgraded_after_opus():
    assert dr._select_composer_model('Проверь архитектуру', [
        {'status': 'ok', 'model': dr.OPUS_MODEL, 'result': 'Expert findings'}]) == dr.QUALITY_COMPOSER_MODEL


def test_initial_requirements_survive_employee_history_packing():
    history = 'ORIGINAL REQUIREMENTS\n' + 'old context\n' * 4000 + 'LATEST FOLLOWUP'
    packed = dr._tail(history, dr.EMPLOYEE_HISTORY_CHARS)
    assert len(packed) <= dr.EMPLOYEE_HISTORY_CHARS
    assert packed.startswith('ORIGINAL REQUIREMENTS')
    assert packed.endswith('LATEST FOLLOWUP')


def test_parallel_workers_wait_for_actual_usage_instead_of_spending_same_budget():
    async def exercise():
        budget = RunBudget(.02)
        first, cap = await budget.reserve_call('gpt-6-sol', 1000, 1024)
        waiting = asyncio.create_task(budget.reserve_call('gpt-6-sol', 1000, 1024))
        await asyncio.sleep(0)
        assert not waiting.done()
        budget.settle(first, 'gpt-6-sol', {'input_tokens': 1000, 'output_tokens': 100})
        second, _ = await asyncio.wait_for(waiting, 1)
        assert budget.spent == pytest.approx(.003)
        assert budget.spent + sum(budget.holds.values()) <= budget.limit
        budget.settle(second, 'gpt-6-sol', None)
        assert budget.unknown > 0
        with pytest.raises(RunBudgetExceeded):
            await budget.reserve_call('gpt-6-sol', 1000, 1024)
    asyncio.run(exercise())


def test_budget_and_outcome_are_separate_from_returning_a_response(monkeypatch):
    monkeypatch.setenv('ORCHESTRATOR_MODEL_BUDGET_USD', '.25')
    with model_trace('web') as state:
        assert current_budget.get().limit == .25
        mark_outcome(accepted=False)
        mark_outcome(artifacts=2)
        assert state['accepted'] is False
    assert current_budget.get() is None


def test_unlimited_orchestrator_still_counts_responses_input_for_its_spend_budget(monkeypatch):
    from types import SimpleNamespace as NS
    from app.billing.call_budget import model_call
    import app.billing.call_budget as cb
    counted, calls = [], []
    async def count(**kwargs):
        counted.append(kwargs)
        return NS(input_tokens=100)
    async def create(**kwargs):
        calls.append(kwargs)
        return NS(usage=NS(input_tokens=100, output_tokens=10))
    monkeypatch.setattr(cb, 'wallet_user', lambda uid: False)
    client = NS(responses=NS(create=create, input_tokens=NS(count=count)))
    async def exercise():
        with run_budget('web'):
            await model_call(client, {'model': 'gpt-6.1-sol', 'input': 'x' * 2_000_000,
                'max_output_tokens': 1024}, model='gpt-6-sol', responses=True)
    asyncio.run(exercise())
    assert len(counted) == len(calls) == 1



def test_bot_report_preserves_stored_per_call_cost_and_legacy_estimates():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[3] / 'botneiro' / 'web_usage.py'
    if not path.exists():
        pytest.skip('Companion bot is not checked out')
    spec = importlib.util.spec_from_file_location('audit_web_usage', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Two web IDs map to one account. One priced row and one legacy aggregate.
    email = 'usage-test@example.test'
    rows = [(42, dr.HAIKU_MODEL, 120_000, 3000, 0, 0, 120_000, 3000, 0, 0, 0, 0, .0135, .0135),
            (module.email_usage_id(email), dr.HAIKU_MODEL, 120_000, 3000, 0, 0, 0, 0, 0, 0, 0, 0)]
    collated = module.collate_web_usage(rows, [(42, 'Example', email)])
    assert len(collated) == 1
    assert collated[0][14] == pytest.approx(.027)
    assert collated[0][15] == pytest.approx(.0135)
    report = module.summarize_web_rows(collated, module.web_model_cost_usd)
    assert report[0]['month'] == pytest.approx(.027)
    assert report[0]['today'] == pytest.approx(.0135)


def test_cost_migration_preserves_legacy_rows_and_is_reversible():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).resolve().parents[1] / 'alembic' / 'versions' / '024_per_call_costs.py'
    spec = importlib.util.spec_from_file_location('cost_migration_024', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite://')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE usage_records (id INTEGER PRIMARY KEY, input_tokens INTEGER)'))
        connection.execute(text('INSERT INTO usage_records VALUES (1, 123)'))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.execute(text('SELECT input_tokens, estimated_usd, cost_is_complete FROM usage_records')).one() == (123, None, 0)
        migration.downgrade()
        assert [c['name'] for c in inspect(connection).get_columns('usage_records')] == ['id', 'input_tokens']



