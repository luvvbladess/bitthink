import asyncio
import json

import pytest
from app.services.code_change_policy import bounded_code_change, code_change_rules
from app.services.orchestrator_policy import ValidationState


@pytest.mark.parametrize('task', [
    'Исправь скидку в pricing.py: сейчас она увеличивает сумму.',
    'Замени >= на > в check.cpp, без рефакторинга.',
    'Добавь проверку пустого списка в parse.rs.',
    'Fix typo in src/App.tsx.',
    'Change timeout from 10 to 15 in settings.json.',
    'Исправь текст кнопки с «Сохрнить» на «Сохранить».',
    'Исправь f.py: комментарий оставь.\n```python\n# refactor security\n```',
    'Исправь f.py: неверный знак. Не меняй test_f.py и unrelated.py.',
])
def test_concrete_edits_keep_one_owner(task):
    assert bounded_code_change(task)


@pytest.mark.parametrize('task', [
    'Тут всё просто, сделай нормально',
    'Исправь авторизацию в auth.py',
    'Fix security vulnerability in auth.py',
    'Add encryption to save.py',
    'Замени архитектуру в app.py',
    'Исправь гонку транзакций в service.py',
    'Добавь миграцию базы данных в migrate.py',
    'Исправь a.py, b.py и c.py',
    'Перепиши service.py с нуля',
    'Исправь app.py и задеплой',
    'Исправь app.py и загрузи на Google Диск',
    'Исправь app.py и отправь письмо',
    'Fix app.py and install dependencies',
    'Добавь шифрование в save.py',
    'Исправь COM SDK в integration.cpp',
    'Добавь новый API в app.py',
    'Fix the entire project in app.py',
    'Объясни, как исправить f.py',
    'Напиши доклад про C++ в DOCX',
])
def test_broad_risky_and_explanatory_work_keeps_normal_route(task):
    assert not bounded_code_change(task)


def test_no_code_rules_on_everyday_answer():
    assert not code_change_rules('Помоги написать сообщение другу')
    assert code_change_rules('Исправь функцию в settings.py')


@pytest.mark.parametrize('receipt', ['Записал f.py (20 байт).', 'Сохранён C:\\demo\\f.py.', '{"ok":true}'])
def test_real_write_then_test_can_finish(receipt):
    s = ValidationState()
    s.observe('workspace_edit', {'path': 'f.py'}, receipt)
    assert not s.checked_after_write
    s.observe('workspace_run', {'argv': ['python', '-m', 'unittest']}, '{"exit_code":0}')
    assert s.checked_after_write and not s.failed
    s.observe('workspace_edit', {'path': 'f.py'}, receipt)
    assert not s.checked_after_write


@pytest.mark.parametrize('receipt', ['Фрагмент не найден. Сначала workspace_read.', '{"error":"denied"}', 'готово'])
def test_failed_or_claimed_write_cannot_finish(receipt):
    s = ValidationState()
    s.observe('workspace_edit', {'path': 'f.py'}, receipt)
    s.observe('workspace_run', {'argv': ['python', '-m', 'unittest']}, '{"exit_code":0}')
    assert not s.checked_after_write


def test_failed_check_or_unrelated_success_cannot_finish():
    s = ValidationState()
    s.observe('workspace_edit', {'path': 'f.py'}, 'Записал f.py (20 байт).')
    s.observe('workspace_run', {'argv': ['python', '-m', 'unittest']}, '{"exit_code":1}')
    s.observe('workspace_run', {'argv': ['python', '-c', 'print("ok")']}, '{"exit_code":0}')
    assert s.failed and not s.checked_after_write
    s.observe('desktop_run_command', {'command': 'dotnet test'}, 'OK\nКод завершения: 0')
    # The failed original check must still be repaired, not hidden by another command.
    assert s.failed


def test_desktop_unittest_and_write_failure_invalidate_completion():
    s = ValidationState()
    s.observe('workspace_edit', {'path': 'f.py'}, 'Сохранён C:\\demo\\f.py.')
    s.observe('desktop_run_command', {'command': 'python -m unittest -v'}, 'OK\nКод завершения: 0')
    assert s.checked_after_write and not s.failed
    s.observe('workspace_edit', {'path': 'f.py'}, 'Фрагмент не найден.')
    s.observe('desktop_run_command', {'command': 'python -m unittest -v'}, 'OK\nКод завершения: 0')
    assert not s.checked_after_write


@pytest.mark.parametrize('desktop,checked', [(False, True), (True, True), (False, False), (True, False)])
@pytest.mark.parametrize('fails_once', [False, True])
def test_bounded_edit_skips_planning(monkeypatch, desktop, checked, fails_once):
    from app.config import get_settings  # noqa: F401
    import director_router as dr
    from app.services.desktop_context import desktop_executor
    from app.services.conversation_context import workspaces
    calls = []

    async def plan(*args, **kw):
        calls.append('plan')
        return {'status': 'done', 'new_employees': []}

    async def worker(item, *args, **kw):
        calls.append(('worker', item['model'], item.get('bounded_code_change')))
        failed = fails_once and len(calls) == 1
        return {'role': item['role'], 'task': item['task'], 'round': 1, 'status': 'error' if failed else 'ok',
                'result': 'Изменено', 'model': item['model'], 'code_change_checked': checked and not failed,
                'validation_failed': failed}

    async def compose(*args, **kw):
        return 'Результат', ''

    async def no_files(*args, **kw):
        return []

    async def forbidden_route(*args, **kw):
        raise AssertionError('A concrete bounded edit needs no routing model')

    monkeypatch.setattr(dr, '_plan_round', plan)
    monkeypatch.setattr(dr, '_execute_employee', worker)
    monkeypatch.setattr(dr, '_compose_answer', compose)
    monkeypatch.setattr(dr, '_new_file_names', no_files)
    monkeypatch.setattr(dr, '_route_turn', forbidden_route)
    monkeypatch.setattr(dr, '_employee_models', lambda uid: ['gpt-6-sol', 'gpt-6-luna'])
    monkeypatch.setattr(dr, '_is_shopping_task', lambda *a: False)
    monkeypatch.setattr(dr, '_turn_has_images', lambda *a: False)
    t = desktop_executor.set((lambda *a: None) if desktop else None)
    w = workspaces.set([])
    try:
        answer = asyncio.run(dr._run_director([], 'Исправь скидку в pricing.py: она увеличивает сумму.', 99, None))
    finally:
        desktop_executor.reset(t)
        workspaces.reset(w)
    assert answer[0] == ('Изменено' if checked else 'Изменение не подтверждено успешной проверкой.\n\nИзменено')
    assert calls[0] == ('worker', 'gpt-6-luna', True)
    assert calls == [('worker', 'gpt-6-luna', True)] * (2 if fails_once else 1)


@pytest.mark.parametrize('desktop', [False, True])
def test_code_worker_limits_tools_and_observes_real_checks(monkeypatch, desktop):
    from app.config import get_settings  # noqa: F401
    from app.services.desktop_context import desktop_executor, desktop_mode
    from app.services.orchestrator_policy import observe_validation
    import director_router as dr
    import openai_client as oc
    seen = []

    async def provider(messages, **options):
        seen.append(options)
        assert 'Задача пользователя:' in messages[-1]['content']
        observe_validation('workspace_edit', {'path': 'f.py'}, 'Сохранён f.py.' if desktop else 'Записал f.py (12 байт).')
        if desktop:
            observe_validation('desktop_run_command', {'command': 'python -m unittest'}, 'OK\nКод завершения: 0')
        else:
            observe_validation('workspace_run', {'argv': ['python', '-m', 'unittest']}, '{"exit_code":0}')
        return 'Исправлено; unittest прошёл.', [], '', []

    monkeypatch.setattr(oc, 'get_chat_response', provider)
    t = desktop_executor.set((lambda *a: None) if desktop else None)
    m = desktop_mode.set('director' if desktop else None)
    try:
        result = asyncio.run(dr._execute_employee({'role': 'Правка кода', 'model': 'gpt-6-luna',
            'task': 'Исправь знак в f.py', 'bounded_code_change': True}, 1, [], 99))
    finally:
        desktop_executor.reset(t)
        desktop_mode.reset(m)
    assert result['status'] == 'ok' and result['code_change_checked']
    opts = seen[0]
    assert opts['max_tool_loops'] == 12 and opts['reasoning_effort'] == 'low'
    assert opts['use_skills'] is False
    assert 'workspace_edit' in opts['allowed_tools']
    assert ('desktop_run_command' in opts['allowed_tools']) is desktop
    assert ('workspace_run' in opts['allowed_tools']) is not desktop
    assert not {'google_drive_upload', 'ssh_exec', 'product_lifecycle'} & opts['allowed_tools']


def test_edit_preview_shows_only_the_replacement_and_ignores_a_failed_write():
    from app.services.code_change_policy import with_edit_preview
    saved = with_edit_preview('workspace_edit', {'path': 'f.py', 'old_string': 'a + 1', 'new_string': 'a - 1'}, 'Сохранён f.py.')
    assert 'Было:\na + 1' in saved and 'Стало:\na - 1' in saved and 'не исправляй' in saved
    assert with_edit_preview('workspace_edit', {'path': 'f.py', 'old_string': 'a', 'new_string': 'b'}, saved) == saved
    missed = 'Фрагмент не найден. Сначала workspace_read.'
    assert with_edit_preview('workspace_edit', {'path': 'f.py', 'old_string': 'a', 'new_string': 'b'}, missed) == missed


@pytest.mark.parametrize('task', [
    'Ну исправь эту проблему',
    'Поправь расчёт скидки, она увеличивает сумму',
    'Fix the crash when the list is empty',
])
def test_project_fix_stays_with_one_coding_agent(task):
    from app.services.code_change_policy import local_project_change
    assert local_project_change(task)


@pytest.mark.parametrize('task', [
    'Почему скидка увеличивается?',
    'Исправь договор и пришли docx',
    'Исправь авторизацию в auth.py',
    'Как исправить эту функцию',
])
def test_questions_documents_and_risky_work_are_not_a_local_patch(task):
    from app.services.code_change_policy import local_project_change
    assert not local_project_change(task)


def test_desktop_fix_uses_one_agent_and_stops(monkeypatch):
    from app.config import get_settings  # noqa: F401
    import director_router as dr
    from app.services.desktop_context import desktop_executor
    calls = []

    async def plan(*args, **kw):
        raise AssertionError('A fix in the open project does not hire another round')

    async def worker(item, *args, **kw):
        calls.append((item['model'], item.get('project_patch'), item.get('bounded_code_change')))
        return {'role': item['role'], 'task': item['task'], 'round': 1, 'status': 'ok',
                'result': 'Исправлено', 'model': item['model'], 'project_patch': True}

    async def compose(*args, **kw):
        raise AssertionError('The coding agent answer is already the result')

    async def no_files(*args, **kw):
        return []

    monkeypatch.setattr(dr, '_plan_round', plan)
    monkeypatch.setattr(dr, '_execute_employee', worker)
    monkeypatch.setattr(dr, '_compose_answer', compose)
    monkeypatch.setattr(dr, '_new_file_names', no_files)
    monkeypatch.setattr(dr, '_employee_models', lambda uid: ['gpt-6-sol', 'gpt-6-luna'])
    monkeypatch.setattr(dr, '_is_shopping_task', lambda *a: False)
    monkeypatch.setattr(dr, '_turn_has_images', lambda *a: False)
    token = desktop_executor.set(lambda *a: None)
    try:
        answer = asyncio.run(dr._run_director([], 'Ну исправь эту проблему', 99, None))
    finally:
        desktop_executor.reset(token)
    assert answer[0] == 'Исправлено'
    assert calls == [('gpt-6-sol', True, None)]


@pytest.mark.parametrize('count', [1, 2])
def test_one_owner_gets_no_instructions_to_poll_imaginary_colleagues(count):
    from app.services.desktop_swarm import execute_swarm_batch, active_agent
    seen = []

    async def execute(employee, *args):
        assert active_agent.get()
        seen.append(employee['task'])
        return {'result': 'checked', 'status': 'ok'}

    hired = [{'task': 'Исправь f.py', 'role': 'Кодер', 'model': 'gpt-6-luna'} for _ in range(count)]
    results = asyncio.run(execute_swarm_batch(hired, 1, [], 99, '', '', False, execute))
    assert len(results) == count and all(r.get('agent_id') for r in results)
    assert all(('swarm_read' in text) is (count > 1) for text in seen)
    if count == 1:
        assert seen == ['Исправь f.py']
