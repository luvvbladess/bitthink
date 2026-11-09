import asyncio

import pytest

from types import SimpleNamespace as NS
from app.services.conversation_context import artifact_context, workspaces

PID = 'a9e97b8238de44ab93d7066e'
HISTORY = [{'role': 'assistant', 'content': 'The result was delivered without a project ID in the prose.'}]


def test_artifacts_are_structured_and_scoped_to_conversation_and_owner():
    file = {'name': f'product-{PID}.zip', 'type': 'generated', 'status': 'done',
            'workspace': {'kind': 'product', 'id': PID}}
    conv = NS(owner_id=1, messages=[NS(role='assistant', attachment=file)])
    assert artifact_context(conv, 1)['workspaces'][0]['product_id'] == PID
    assert artifact_context(conv, 2)['workspaces'] == []
    assert artifact_context(NS(owner_id=1, messages=[]), 1)['workspaces'] == []
    assert artifact_context(conv, 2)['files'][0]['name'] == file['name']
    conv.messages = [NS(role='user', attachment=file)]
    assert artifact_context(conv, 1)['workspaces'] == []
    conv.messages = [NS(role='assistant', attachment={}, content=f'product-{PID}.zip')]
    assert artifact_context(conv, 1)['workspaces'] == []


def test_legacy_generated_archive_metadata_is_available_without_parsing_chat_prose():
    conv = NS(owner_id=1, messages=[NS(role='assistant', attachment={'name': f'product-{PID}.zip', 'type': 'generated'})])
    assert artifact_context(conv, 1)['workspaces'][0]['product_id'] == PID


@pytest.mark.parametrize('decision', ['none', 'create'])
def test_planner_keeps_question_and_new_product_separate_from_existing_project(decision):
    import director_router as dr
    token = workspaces.set([{'product_id': PID, 'artifact': 'result.zip'}])
    try:
        plan = dr._parse_director_plan(__import__('json').dumps({'status': 'done', 'workspace_action': decision}), strict=True)
        assert plan['workspace_action'] == decision
        assert 'workspace_id' not in plan
        with pytest.raises(ValueError):
            dr._parse_director_plan('{"status":"continue","workspace_action":"revise","workspace_id":"wrong"}', strict=True)
        with pytest.raises(ValueError):
            dr._parse_director_plan('{"status":"done"}', strict=True)
    finally:
        workspaces.reset(token)


@pytest.mark.parametrize('text', [
    'Создай сайт для учёта заказов',
    'Сделай сайт по этому промпту: тёмная тема и форма заявки',
    'По промпту ниже собери лендинг кофейни',
    'Напиши промпт и собери по нему лендинг',
])
def test_empty_registry_still_uses_semantic_product_decision(monkeypatch, text):
    import director_router as dr
    from app.services import autonomy
    from conversations import conversation_manager
    executed = []
    async def plan(*args, **kwargs):
        return {'status': 'continue', 'new_employees': [], 'workspace_action': 'create'}
    async def employee(item, round_num, journal, uid, *args):
        executed.append(item['product_phase'])
        autonomy.product_evidence.get().update(product_id=PID, path=f'products/{PID}', stack='static', ready=False, packaged=False)
        return {'round': round_num, 'role': item['role'], 'task': item['task'], 'model': item['model'], 'status': 'ok', 'result': 'Built'}
    async def verified(*args, **kwargs):
        return {'product_id': PID, 'path': f'products/{PID}', 'stack': 'static', 'ready': len(executed) >= 2,
                'packaged': len(executed) >= 2, 'archive': f'product-{PID}.zip'}
    async def no_files(*args):
        return []
    monkeypatch.setattr(dr, '_plan_round', plan)
    monkeypatch.setattr(dr, '_execute_employee', employee)
    monkeypatch.setattr(dr, '_new_file_names', no_files)
    monkeypatch.setattr(dr, '_is_document_package_task', lambda *args: False)
    monkeypatch.setattr(dr, '_is_shopping_task', lambda *args: False)
    monkeypatch.setattr(dr, '_employee_models', lambda uid: list(dr.MODEL_POOL))
    monkeypatch.setattr(conversation_manager, 'get_subscription', lambda uid: {'tier': 'creator'})
    monkeypatch.setattr(autonomy, 'verified_product', verified)
    monkeypatch.setattr(autonomy, 'learn', lambda *args: None)
    context_token = workspaces.set([])
    product_token = autonomy.product_evidence.set({})
    try:
        answer, _, _, _ = asyncio.run(dr._run_director([], text, 92001, None))
        assert executed == ['brief', 'build']
        assert '[!SUCCESS]' in answer and 'Сборка' in answer and 'Тесты' in answer
    finally:
        workspaces.reset(context_token)
        autonomy.product_evidence.reset(product_token)


@pytest.mark.parametrize('text', [
    'Нужна удобная штука для учёта заказов',
    'создай полноценный доклад про частицу тахеон, оформи в ворд и положи на гугл диск',
    'сделай промпт для сайта кофейни',
    'напиши промпт, по которому можно создать лендинг',
    'Разработай ТЗ на сайт, сам сайт не собирай',
    'сделай доклад про сайт конкурента',
    'не создавай сайт, напиши промпт для него',
    'Create a prompt for a landing page',
    'Напиши промпт для сайта.\nСоздай современный лендинг кофейни, тёмная тема',
    'сделай кнопку для сайта',
])
def test_ordinary_request_does_not_start_product_acceptance(monkeypatch, text):
    import director_router as dr
    from app.services import autonomy
    from conversations import conversation_manager
    phases = []

    async def plan(*args, **kwargs):
        return {'status': 'continue', 'new_employees': [], 'workspace_action': 'create'}

    async def employee(item, round_num, journal, uid, *args):
        phases.append(item.get('product_phase'))
        return {'round': round_num, 'role': item['role'], 'task': item['task'], 'model': item['model'],
                'status': 'ok', 'result': 'Файл записан'}

    async def no_files(*args):
        return []

    async def compose(*args, **kwargs):
        return 'Файл готов.', ''

    async def direct(*args, **kwargs):
        return 'Обычный ответ', '', []

    monkeypatch.setattr(dr, '_plan_round', plan)
    monkeypatch.setattr(dr, '_execute_employee', employee)
    monkeypatch.setattr(dr, '_new_file_names', no_files)
    monkeypatch.setattr(dr, '_compose_answer', compose)
    monkeypatch.setattr(dr, '_answer_directly', direct)
    monkeypatch.setattr(dr, '_is_document_package_task', lambda *args: False)
    monkeypatch.setattr(dr, '_is_shopping_task', lambda *args: False)
    monkeypatch.setattr(dr, '_employee_models', lambda uid: list(dr.MODEL_POOL))
    monkeypatch.setattr(conversation_manager, 'get_subscription', lambda uid: {'tier': 'creator'})
    context_token = workspaces.set([])
    product_token = autonomy.product_evidence.set({})
    try:
        answer, _, _, _ = asyncio.run(dr._run_director([], text, 92001, None))
    finally:
        workspaces.reset(context_token)
        autonomy.product_evidence.reset(product_token)
    assert 'brief' not in phases and 'build' not in phases
    assert '[!SUCCESS]' not in answer
    assert 'Сборка и тесты' not in answer
    assert 'Браузерная проверка' not in answer


@pytest.mark.parametrize('source_available, failed_check, repair_passes', [
    (True, False, False), (False, False, False), (True, True, True), (True, True, False),
])
def test_followup_revises_existing_sources_before_acceptance(monkeypatch, source_available, failed_check, repair_passes):
    import director_router as dr
    from conversations import conversation_manager
    from app.services import autonomy, sandbox_client
    from app.services.desktop_context import desktop_executor
    executed, revisions, checks = [], [], []
    base = {'product_id': PID, 'path': f'products/{PID}', 'brief': 'Сайт переработки лития. Сине-серое оформление.',
            'stack': 'static', 'ready': not failed_check, 'packaged': not failed_check,
            'archive': f'product-{PID}.zip', 'revision': 'rev'}
    if failed_check:
        base['checks'] = {'test': {'passed': False, 'revision': 'rev', 'exit_code': 1, 'output': 'TypeError: bad state'}}
    text = 'почини сайт' if failed_check else 'шрифты бы покрупнее, больше анимаций'
    async def verified(uid, pid, package=False):
        assert uid == 92001 and pid == PID
        checks.append(package)
        if not source_available:
            return {'error': 'Not found for this user'}
        ready = len(executed) >= (2 if failed_check and not repair_passes else 1)
        return {**base, 'ready': ready, 'packaged': ready} if package else base
    async def tool(name, args, uid):
        assert name == 'product_lifecycle' and uid == 92001
        assert args['action'] == 'begin_revision' and args['product_id'] == PID
        assert 'Сайт переработки лития' in args['brief'] and text in args['brief']
        revisions.append(args)
        return __import__('json').dumps({**base, 'ready': False, 'packaged': False})
    async def employee(item, round_num, journal, uid, *args):
        assert revisions and checks[0] is False
        assert item['product_phase'] == 'build'
        assert f'products/{PID}' in item['task']
        assert text in item['task']
        if failed_check and not executed:
            assert item['product_repair']
            assert 'TypeError: bad state' in item['task']
            assert item['model'] == dr.PLANNER_MODEL
            if not repair_passes:
                autonomy.product_evidence.get()['_repair_edits'] = ['Подтверждённое изменение app.js']
        else:
            assert not item.get('product_repair')
            if failed_check:
                assert 'Подтверждённое изменение app.js' in item['task']
                assert 'Свежий вывод test' in item['task']
        executed.append(item)
        return {'round': round_num, 'role': item['role'], 'task': item['task'], 'model': item['model'],
                'status': 'ok', 'result': 'Edited', 'product_repair': bool(item.get('product_repair'))}
    async def no_files(*args):
        return []
    async def no_plan(*args, **kwargs):
        return {'status': 'continue', 'new_employees': [], 'workspace_action': 'revise', 'workspace_id': PID}
    monkeypatch.setattr(autonomy, 'verified_product', verified)
    monkeypatch.setattr(autonomy, 'learn', lambda *args: None)
    monkeypatch.setattr(sandbox_client, 'run_workspace_tool', tool)
    monkeypatch.setattr(dr, '_execute_employee', employee)
    monkeypatch.setattr(dr, '_plan_round', no_plan)
    monkeypatch.setattr(dr, '_compose_answer', no_plan)
    monkeypatch.setattr(dr, '_new_file_names', no_files)
    monkeypatch.setattr(dr, '_is_document_package_task', lambda *args: False)
    monkeypatch.setattr(dr, '_is_shopping_task', lambda *args: False)
    monkeypatch.setattr(dr, '_employee_models', lambda uid: list(dr.MODEL_POOL))
    monkeypatch.setattr(conversation_manager, 'get_subscription', lambda uid: {'tier': 'creator'})
    product_token = autonomy.product_evidence.set({})
    desktop_token = desktop_executor.set(None)
    context_token = workspaces.set([{'product_id': PID, 'artifact': f'product-{PID}.zip'}])
    try:
        answer, _, _, _ = asyncio.run(dr._run_director(HISTORY, text, 92001, None))
    finally:
        autonomy.product_evidence.reset(product_token)
        desktop_executor.reset(desktop_token)
        workspaces.reset(context_token)
    if source_available:
        assert len(executed) == (2 if failed_check and not repair_passes else 1)
        assert '[!SUCCESS]' in answer and 'Сборка' in answer and 'Тесты' in answer
        assert revisions[0]['product_id'] == PID
    else:
        assert executed == [] and revisions == []
        assert 'Прикрепите выданный ZIP-архив' in answer


def test_focused_repair_requires_a_current_reproducible_failure_and_scopes_edits():
    from app.services.autonomy import focused_product_repair, repair_tool_allowed
    root = f'products/{PID}'
    failure = {'passed': False, 'exit_code': 1, 'revision': 'rev', 'output': 'AssertionError'}
    project = {'product_id': PID, 'path': root, 'stack': 'static', 'revision': 'rev',
               'checks': {'test': failure}}
    assert 'build, test и smoke' in focused_product_repair('почини, пожалуйста', project)
    assert not focused_product_repair('почини и перепиши архитектуру', project)
    assert not focused_product_repair('почини', {**project, 'revision': 'different'})
    for code in (124, 127):
        assert not focused_product_repair('почини', {**project, 'checks': {'test': {**failure, 'exit_code': code}}})
    scope = (PID, root)
    assert repair_tool_allowed('workspace_edit', {'path': f'{root}/src/app.js'}, scope)
    assert repair_tool_allowed('workspace_read', {'path': f'{root}/tests/app.test.js'}, scope)
    for path in (f'{root}/tests/app.test.js', f'{root}/package.json', f'{root}/../other/app.js'):
        assert not repair_tool_allowed('workspace_edit', {'path': path}, scope)
    assert not repair_tool_allowed('workspace_write', {'path': f'{root}/src/app.js'}, scope)
    assert not repair_tool_allowed('product_lifecycle', {'product_id': PID, 'action': 'package'}, scope)
    assert not repair_tool_allowed('product_lifecycle', {'product_id': 'different', 'action': 'test'}, scope)


@pytest.mark.parametrize('text, revises', [
    ('сделай промпт для этого сайта', False),
    ('напиши промпт, по которому можно доработать этот сайт', False),
    ('Напиши промпт для сайта.\nСоздай современный лендинг', False),
    ('добавь форму заявки на сайт', True),
])
def test_existing_project_follows_the_requested_result(monkeypatch, text, revises):
    import director_router as dr
    from conversations import conversation_manager
    from app.services import autonomy, sandbox_client
    from app.services.desktop_context import desktop_executor
    planned, revisions, phases = [], [], []
    base = {'product_id': PID, 'path': f'products/{PID}', 'brief': 'Сайт кофейни.',
            'stack': 'static', 'ready': True, 'packaged': True, 'archive': f'product-{PID}.zip'}

    async def verified(uid, pid, package=False):
        return {**base, 'ready': bool(phases), 'packaged': bool(phases)} if package else base

    async def tool(name, args, uid):
        revisions.append(args)
        return __import__('json').dumps({**base, 'ready': False, 'packaged': False})

    async def employee(item, round_num, journal, uid, *args):
        phases.append(item.get('product_phase'))
        return {'round': round_num, 'role': item['role'], 'task': item['task'], 'model': item['model'],
                'status': 'ok', 'result': 'Edited'}

    async def plan(*args, **kwargs):
        planned.append(args[0] if args else text)
        return {'status': 'continue', 'new_employees': [], 'workspace_action': 'revise', 'workspace_id': PID}

    async def direct(*args, **kwargs):
        return 'Вот промпт', '', []

    monkeypatch.setattr(autonomy, 'verified_product', verified)
    monkeypatch.setattr(autonomy, 'learn', lambda *args: None)
    monkeypatch.setattr(sandbox_client, 'run_workspace_tool', tool)
    monkeypatch.setattr(dr, '_execute_employee', employee)
    monkeypatch.setattr(dr, '_plan_round', plan)
    monkeypatch.setattr(dr, '_answer_directly', direct)
    monkeypatch.setattr(dr, '_compose_answer', direct)
    async def no_files(*args):
        return []

    monkeypatch.setattr(dr, '_new_file_names', no_files)
    monkeypatch.setattr(dr, '_is_document_package_task', lambda *args: False)
    monkeypatch.setattr(dr, '_is_shopping_task', lambda *args: False)
    monkeypatch.setattr(dr, '_employee_models', lambda uid: list(dr.MODEL_POOL))
    monkeypatch.setattr(conversation_manager, 'get_subscription', lambda uid: {'tier': 'creator'})
    product_token = autonomy.product_evidence.set({})
    desktop_token = desktop_executor.set(None)
    context_token = workspaces.set([{'product_id': PID, 'artifact': f'product-{PID}.zip'}])
    try:
        answer, _, _, _ = asyncio.run(dr._run_director(HISTORY, text, 92001, None))
    finally:
        autonomy.product_evidence.reset(product_token)
        desktop_executor.reset(desktop_token)
        workspaces.reset(context_token)
    if revises:
        assert planned and revisions and phases == ['build']
        assert '[!SUCCESS]' in answer
    else:
        assert planned == [] and revisions == [] and phases == []
        assert answer == 'Вот промпт' and '[!SUCCESS]' not in answer


@pytest.mark.parametrize('text, action, builds', [
    ('Создай сайт для учёта заказов', 'reply', False),
    ('сделай промпт для сайта кофейни', 'product', True),
])
def test_model_route_overrides_keyword_guess(monkeypatch, text, action, builds):
    import director_router as dr
    from app.services import autonomy
    from conversations import conversation_manager
    phases = []

    async def route(*args, **kwargs):
        return {'action': action, 'goal': 'проверка маршрута', 'workspace_id': ''}

    async def plan(*args, **kwargs):
        return {'status': 'continue', 'new_employees': [], 'workspace_action': 'create'}

    async def employee(item, round_num, journal, uid, *args):
        phases.append(item.get('product_phase'))
        autonomy.product_evidence.get().update(product_id=PID, path=f'products/{PID}', stack='static', ready=False, packaged=False)
        return {'round': round_num, 'role': item['role'], 'task': item['task'], 'model': item['model'],
                'status': 'ok', 'result': 'Built'}

    async def verified(*args, **kwargs):
        return {'product_id': PID, 'path': f'products/{PID}', 'stack': 'static', 'ready': len(phases) >= 2,
                'packaged': len(phases) >= 2, 'archive': f'product-{PID}.zip'}

    async def direct(*args, **kwargs):
        return 'Обычный ответ', '', []

    monkeypatch.setattr(dr, '_route_turn', route)
    monkeypatch.setattr(dr, '_plan_round', plan)
    monkeypatch.setattr(dr, '_execute_employee', employee)
    monkeypatch.setattr(dr, '_new_file_names', lambda *args: _empty())
    monkeypatch.setattr(dr, '_answer_directly', direct)
    monkeypatch.setattr(dr, '_compose_answer', direct)
    monkeypatch.setattr(dr, '_is_document_package_task', lambda *args: False)
    monkeypatch.setattr(dr, '_is_shopping_task', lambda *args: False)
    monkeypatch.setattr(dr, '_employee_models', lambda uid: list(dr.MODEL_POOL))
    monkeypatch.setattr(conversation_manager, 'get_subscription', lambda uid: {'tier': 'creator'})
    monkeypatch.setattr(autonomy, 'verified_product', verified)
    monkeypatch.setattr(autonomy, 'learn', lambda *args: None)
    context_token = workspaces.set([])
    product_token = autonomy.product_evidence.set({})
    try:
        answer, _, _, _ = asyncio.run(dr._run_director([], text, 92001, None))
    finally:
        workspaces.reset(context_token)
        autonomy.product_evidence.reset(product_token)
    if builds:
        assert phases == ['brief', 'build'] and '[!SUCCESS]' in answer
    else:
        assert phases == [] and answer == 'Обычный ответ' and '[!SUCCESS]' not in answer


async def _empty():
    return []
