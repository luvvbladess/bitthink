import asyncio
import hashlib
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from app.config import get_settings
from app.services import product_factory as factory
from app.services import workspace_fs as fs
from app.services import autonomy
from app.services.product_strategy import is_product_request, select_stack
from app.services.product_benchmark import evaluate
from app.services.self_improvement import validate_proposal, ALLOWED_PATH


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('WORKSPACES_DIR', str(tmp_path / 'workspaces'))
    monkeypatch.setenv('WORKSPACE_ALLOW_LOCAL_RUN', '1')
    monkeypatch.delenv('SANDBOX_MODE', raising=False)
    monkeypatch.delenv('WORKSPACE_LANDLOCK', raising=False)
    monkeypatch.setattr(get_settings(), 'DATA_DIR', tmp_path / 'data')
    return tmp_path


def start(uid=92001, stack='python'):
    result = factory.operate(uid, {'action': 'start', 'brief': 'Создай приложение для вычисления скидок', 'stack': stack})
    root = fs.user_root(uid) / result['path']
    (root / 'BRIEF.md').write_text('Вычислять скидку и отклонять неверные входные данные.', encoding='utf-8')
    (root / 'README.md').write_text('Запуск: python calculator.py; тесты: python -m unittest discover -s tests.', encoding='utf-8')
    (root / 'tests').mkdir()
    (root / 'calculator.py').write_text('def discount(price, rate):\n    return price * (1 - rate)\n', encoding='utf-8')
    (root / 'tests/test_calculator.py').write_text(
        'import unittest\nfrom calculator import discount\nclass Discount(unittest.TestCase):\n'
        '    def test_discount(self):\n        self.assertEqual(discount(100, .2), 80)\n', encoding='utf-8')
    return result, root


def operation(state, action, uid=92001):
    return factory.operate(uid, {'action': action, 'product_id': state['product_id']})


def test_real_python_product_build_test_archive_and_stale_evidence(workspace):
    state, root = start()
    assert operation(state, 'build')['last_check']['exit_code'] == 0
    assert operation(state, 'test')['ready']
    packaged = operation(state, 'package')
    assert packaged['packaged']
    archive = fs.user_root(92001) / packaged['archive']
    with zipfile.ZipFile(archive) as stream:
        assert {'calculator.py', 'README.md', 'tests/test_calculator.py', 'BITTHINK_CHECKS.json'} <= set(stream.namelist())
        assert not any('__pycache__' in name for name in stream.namelist())
    (root / 'calculator.py').write_text('def discount(price, rate):\n    return 0\n', encoding='utf-8')
    assert not operation(state, 'status')['ready']
    assert not operation(state, 'status')['packaged']
    with pytest.raises(ValueError, match='успешной'):
        operation(state, 'package')
    failure = operation(state, 'test')
    assert not failure['ready'] and failure['last_check']['exit_code'] != 0


def test_products_and_receipts_are_private_and_unforgeable_through_workspace_tools(workspace):
    state, root = start()
    (root / 'receipt.json').write_text('{"ready": true}', encoding='utf-8')
    assert not operation(state, 'status')['ready']
    with pytest.raises(ValueError):
        operation(state, 'status', uid=92002)
    with pytest.raises(ValueError):
        fs.resolve_in_jail(92001, '../.product-control/u92001/' + state['product_id'] + '.json')
    for pid in ['../escape', '/etc/passwd', 'a' * 25, '']:
        assert 'error' in json.loads(factory.dispatch(92001, {'action': 'status', 'product_id': pid}))


def test_real_static_build_detects_missing_assets(workspace):
    state, root = start(stack='static')
    (root / 'index.html').write_text('<html><head><title>Coffee</title></head><body><img src="missing.png"></body></html>', encoding='utf-8')
    result = operation(state, 'build')
    assert not result['gates']['build'] and 'missing.png' in result['last_check']['output']
    (root / 'missing.png').write_bytes(b'image fixture')
    assert operation(state, 'build')['gates']['build']


def test_empty_tests_do_not_count_as_acceptance(workspace):
    state, root = start()
    (root / 'tests/test_calculator.py').unlink()
    with pytest.raises(ValueError, match='реальные тесты'):
        operation(state, 'test')
    (root / 'tests/test_empty.py').write_text('# no assertions\n', encoding='utf-8')
    assert not operation(state, 'test')['gates']['test']


def test_check_that_rewrites_sources_is_not_a_receipt(workspace, monkeypatch):
    state, root = start()
    def change(*args, **kwargs):
        (root / 'calculator.py').write_text('print("changed during build")', encoding='utf-8')
        return {'exit_code': 0, 'passed': True, 'output': 'ok'}
    monkeypatch.setattr(factory, '_command', change)
    assert not operation(state, 'build')['gates']['build']


def test_private_lessons_require_current_checked_product(workspace):
    state, root = start()
    lesson = {'problem': 'Неверно рассчитана скидка', 'cause': 'Не учитывалась доля процента', 'standard': 'Считать скидку как цену, умноженную на один минус долю.'}
    with pytest.raises(ValueError):
        autonomy.learn(92001, lesson, operation(state, 'status'))
    operation(state, 'build')
    operation(state, 'test')
    autonomy.learn(92001, lesson, operation(state, 'package'))
    assert autonomy.recall(92001, 'скидка')[0]['standard'] == lesson['standard']
    assert autonomy.recall(92002) == []


def test_product_dependency_chain_and_retry_limit():
    first = autonomy.product_employee('Сделай сайт', {}, [])
    assert first['product_phase'] == 'brief' and 'product_lifecycle' in first['task']
    second = autonomy.product_employee('Сделай сайт', {'product_id': 'id', 'path': 'products/id', 'stack': 'static'}, [])
    assert second['product_phase'] == 'build'
    assert autonomy.product_employee('Сделай сайт', {'packaged': True}, []) is None
    assert autonomy.product_employee('Сделай сайт', {}, [{'product_phase': 'build'}] * 5) is None


def test_stack_selection_benchmark():
    result = evaluate()
    assert result['passed'] == result['total'], [item for item in result['cases'] if not item['passed']]


def test_web_product_cannot_skip_browser_acceptance(workspace, monkeypatch):
    state, root = start(stack='static')
    (root / 'index.html').write_text('<html><title>Product</title><body>Working product</body></html>', encoding='utf-8')
    monkeypatch.setattr(factory, '_command', lambda *args, **kwargs: {'passed': True, 'exit_code': 0, 'output': 'tests passed'})
    operation(state, 'build')
    result = operation(state, 'test')
    assert result['gates']['build'] and result['gates']['test'] and not result['gates']['smoke']
    with pytest.raises(ValueError):
        operation(state, 'package')
    assert operation(state, 'smoke')['ready']


def test_receipts_are_invalid_after_deleting_archive(workspace):
    state, root = start()
    operation(state, 'build'); operation(state, 'test')
    status = operation(state, 'package')
    (fs.user_root(92001) / status['archive']).unlink()
    assert not operation(state, 'status')['packaged']


def test_new_requirements_invalidate_previous_acceptance_without_source_edits(workspace):
    state, root = start()
    operation(state, 'build'); operation(state, 'test'); operation(state, 'package')
    result = factory.operate(92001, {'action': 'revise', 'product_id': state['product_id'],
                                    'brief': 'Добавь расчёт налога и проверку отрицательных значений.'})
    assert not result['ready'] and not result['packaged'] and result['checks'] == {}
    assert 'налога' in result['brief']
    with pytest.raises(ValueError):
        operation(state, 'package')


def test_responses_loop_stops_after_verified_tool_before_later_mutation(workspace, monkeypatch):
    import openai_client as oc
    import computer_tools as ct
    import runtime_context as rc
    from app.billing import call_budget as cb
    called, settled, requests = [], [], []
    async def model_call(client, request, **kwargs):
        requests.append(request)
        assert len(requests) == 1, 'No extra model call after acceptance'
        return NS(status='completed', usage=None, output=[
            NS(type='function_call', name='product_lifecycle', arguments='{"action":"smoke"}', call_id='accept', id='accept'),
            NS(type='function_call', name='workspace_write', arguments='{"path":"late.py","content":"bad change"}', call_id='late', id='late'),
        ])
    async def execute(name, args, uid):
        called.append(name)
        return '{"ready":true}'
    async def settle(*args, **kwargs):
        settled.append(True)
    monkeypatch.setattr(cb, 'model_call', model_call)
    monkeypatch.setattr(cb, 'wallet_user', lambda uid: False)
    monkeypatch.setattr(ct, 'run_computer_tool', execute)
    monkeypatch.setattr(oc, '_settle_model_usage', settle)
    monkeypatch.setattr(rc, 'with_runtime_context', lambda messages, **kwargs: messages)
    answer, _, _, _ = asyncio.run(oc.get_chat_response([{'role': 'user', 'content': 'Создай продукт'}],
        model='gpt-6-luna', user_id=92001, allowed_tools=frozenset({'product_lifecycle', 'workspace_write'}),
        stop_after_tool=lambda name, result: name == 'product_lifecycle' and json.loads(result).get('ready')))
    assert called == ['product_lifecycle'] and settled == [True]
    assert 'Проверки продукта пройдены' in answer


@pytest.mark.parametrize('text', ['Создай сайт', 'Разработай приложение', 'Build a website', 'Создай Telegram бота'])
def test_explicit_product_requests(text):
    assert is_product_request(text)


def test_company_standard_is_shared_and_blocks_unproven_delivery():
    plain = [{'role': 'system', 'content': 'Обычный чат'}]
    once = autonomy.attach_company(plain)
    assert once[1]['content'].startswith('Компания BitThink')
    assert autonomy.attach_company(once) == once
    assert 'company-tps-v1' in autonomy.RULES
    bare = autonomy.release_guard('Архив готов, скачайте кнопкой в чате.', [])
    assert 'не приложен' in bare and 'Скачивать нечего' in bare
    kept = autonomy.release_guard('Архив готов, скачайте кнопкой в чате.', [{'bytes': b'zip'}])
    assert 'скачайте кнопкой' in kept
    published = autonomy.release_guard('Я опубликовал сайт.', [])
    assert 'публикация не выполнялась' in published and 'Публикация не подтверждена' in published
    story = autonomy.release_guard('Автор опубликовал роман в 1866 году.', [])
    assert 'роман' in story and 'не выполнялась' not in story

    class Record:
        engineering = {'last_build_failed': True}

    stopped = autonomy.release_guard('Предварительная модель собрана.', [], Record())
    assert 'не допущенный комплект' in stopped


def test_self_improvement_does_not_grant_permission_to_edit_release_policy():
    source = Path(__file__).parents[1].joinpath('app/services/product_strategy.py').read_text(encoding='utf-8')
    proposal = {'path': ALLOWED_PATH, 'base_sha256': hashlib.sha256(source.encode()).hexdigest(), 'source': source}
    assert validate_proposal(source, proposal) == source
    for patch in [dict(proposal, path='backend/app/auth.py'), dict(proposal, source=source + '\nimport os\n'),
                  dict(proposal, source=source + '\nexec("code")\n'), dict(proposal, base_sha256='stale')]:
        with pytest.raises(ValueError):
            validate_proposal(source, patch)


def test_tool_catalog_and_dispatch(workspace):
    from computer_tools import COMPUTER_TOOL_NAMES, run_computer_tool
    assert {'product_lifecycle', 'autonomy'} <= COMPUTER_TOOL_NAMES
    charter = json.loads(asyncio.run(run_computer_tool('autonomy', {'action': 'identity'}, 92001)))
    assert charter['version'] == autonomy.VERSION and 'PDCA' in ' '.join(charter['principles'])
    assert {item['name'] for item in charter['departments']} >= {'Оркестратор', 'Сайт', 'Документы и Студия', 'Поиск', 'Качество'}
    state = json.loads(fs.dispatch(92001, 'product', {'action': 'start', 'brief': 'Сделай лендинг'}))
    assert state['stack'] == 'static'


@pytest.mark.parametrize('complete', [False, True])
def test_actual_orchestrator_requires_tool_evidence_and_preserves_project(workspace, monkeypatch, complete):
    import director_router as dr
    from conversations import conversation_manager
    from computer_tools import run_computer_tool
    monkeypatch.delenv('SANDBOX_URL', raising=False)
    monkeypatch.setattr(dr, '_employee_models', lambda uid: list(dr.MODEL_POOL))
    monkeypatch.setattr(conversation_manager, 'get_subscription', lambda uid: {'tier': 'creator'})
    monkeypatch.setattr(dr, '_is_document_package_task', lambda text: False)
    monkeypatch.setattr(dr, '_is_shopping_task', lambda *args: False)
    async def names(*args):
        return []
    async def compose(*args, **kwargs):
        return 'Всё готово и опубликовано (неподтверждённое заявление модели)', ''
    async def plan(*args, **kwargs):
        return {'status': 'continue', 'new_employees': []}
    monkeypatch.setattr(dr, '_new_file_names', names)
    monkeypatch.setattr(dr, '_compose_answer', compose)
    monkeypatch.setattr(dr, '_plan_round', plan)
    rounds = []
    async def employee(item, round_num, journal, uid, *args):
        rounds.append(item['product_phase'])
        if item['product_phase'] == 'brief':
            state, root = start(uid)
            await run_computer_tool('product_lifecycle', {'action': 'status', 'product_id': state['product_id']}, uid)
        elif complete:
            state = autonomy.product_evidence.get()
            # Model stops after checks; the controller must still produce the ZIP.
            for action in ('build', 'test'):
                await run_computer_tool('product_lifecycle', {'action': action, 'product_id': state['product_id']}, uid)
        return {'round': round_num, 'role': item['role'], 'status': 'ok', 'result': 'Готово по мнению сотрудника',
                'model': item['model'], 'product_phase': item['product_phase']}
    monkeypatch.setattr(dr, '_execute_employee', employee)
    token = autonomy.product_evidence.set({})
    try:
        answer, _, _, _ = asyncio.run(dr._run_director([], 'Создай приложение для скидок', 92001, None))
    finally:
        autonomy.product_evidence.reset(token)
    assert rounds[:2] == ['brief', 'build']
    if complete:
        assert 'Сборка и тесты текущей версии пройдены' in answer
        assert len(rounds) == 2
    else:
        assert 'Готовность не подтверждена' in answer
        assert 'Всё готово и опубликовано' not in answer
        assert len(rounds) == 5
