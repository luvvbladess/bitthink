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


def test_empty_registry_still_uses_semantic_product_decision(monkeypatch):
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
        answer, _, _, _ = asyncio.run(dr._run_director([], 'Нужна удобная штука для учёта заказов', 92001, None))
        assert executed == ['brief', 'build']
        assert 'Сборка и тесты текущей версии пройдены' in answer
    finally:
        workspaces.reset(context_token)
        autonomy.product_evidence.reset(product_token)


@pytest.mark.parametrize('source_available', [True, False])
def test_followup_revises_existing_sources_before_acceptance(monkeypatch, source_available):
    import director_router as dr
    from conversations import conversation_manager
    from app.services import autonomy, sandbox_client
    from app.services.desktop_context import desktop_executor
    executed, revisions, checks = [], [], []
    base = {'product_id': PID, 'path': f'products/{PID}', 'brief': 'Сайт переработки лития. Сине-серое оформление.',
            'stack': 'static', 'ready': True, 'packaged': True, 'archive': f'product-{PID}.zip'}
    async def verified(uid, pid, package=False):
        assert uid == 92001 and pid == PID
        checks.append(package)
        if not source_available:
            return {'error': 'Not found for this user'}
        return {**base, 'ready': bool(executed), 'packaged': bool(executed)} if package else base
    async def tool(name, args, uid):
        assert name == 'product_lifecycle' and uid == 92001
        assert args['action'] == 'revise' and args['product_id'] == PID
        assert 'Сайт переработки лития' in args['brief'] and 'шрифты бы покрупнее' in args['brief']
        revisions.append(args)
        return __import__('json').dumps({**base, 'ready': False, 'packaged': False})
    async def employee(item, round_num, journal, uid, *args):
        assert revisions and checks[0] is False
        assert item['product_phase'] == 'build'
        assert f'products/{PID}' in item['task']
        assert 'шрифты бы покрупнее' in item['task']
        executed.append(item)
        return {'round': round_num, 'role': item['role'], 'task': item['task'], 'model': item['model'], 'status': 'ok', 'result': 'Edited'}
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
        answer, _, _, _ = asyncio.run(dr._run_director(HISTORY, 'шрифты бы покрупнее, больше анимаций', 92001, None))
    finally:
        autonomy.product_evidence.reset(product_token)
        desktop_executor.reset(desktop_token)
        workspaces.reset(context_token)
    if source_available:
        assert len(executed) == 1
        assert 'Сборка и тесты текущей версии пройдены' in answer
        assert revisions[0]['product_id'] == PID
    else:
        assert executed == [] and revisions == []
        assert 'Прикрепите выданный ZIP-архив' in answer
