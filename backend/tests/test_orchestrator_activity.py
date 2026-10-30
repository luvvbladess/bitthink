import asyncio

import pytest

from orchestrator_activity import employee_activity, tool_activity
from status_feed import announce_tool, bind_status, push_status


@pytest.mark.parametrize('tool,args,kind,title', [
    ('workspace_read', {'path': '/private/project/Договор.docx'}, 'file', 'Читаю материалы задачи'),
    ('workspace_write', {'path': r'C:\private\Таблица.xlsx'}, 'file', 'Создаю таблицу'),
    ('python_run', {'path': '/private/internal_calc.py'}, 'work', 'Обрабатываю данные для задачи'),
    ('pip_install', {'packages': ['internal-package']}, 'prepare', 'Подготавливаю инструменты'),
    ('product_lifecycle', {'action': 'test'}, 'check', 'Запускаю проверки проекта'),
    ('product_lifecycle', {'action': 'package'}, 'file', 'Упаковываю проект для скачивания'),
    ('ssh_exec', {'command': 'echo secret-value'}, 'ssh', 'Выполняю действие'),
    ('http_request', {'path': '/private?token=secret-value'}, 'api', 'Обращаюсь'),
    ('swarm_read', {}, 'work', 'Сверяю промежуточные результаты'),
    ('swarm_publish', {'summary': 'private findings'}, 'work', 'Передаю результаты для дальнейшей работы'),
    ('swarm_send', {'recipient': 'internal-id'}, 'work', 'Согласовываю детали выполнения задачи'),
])
def test_tools_describe_actions_without_commands_or_internal_paths(tool, args, kind, title):
    action_kind, text = tool_activity(tool, args)
    assert action_kind == kind
    assert text.startswith(title)
    assert 'private' not in text and 'secret-value' not in text and 'internal_' not in text


def test_employee_label_does_not_echo_internal_assignment():
    kind, text = employee_activity({'role': 'Проверка результата', 'task': 'secret instructions', 'model': 'internal-model'})
    assert kind == 'check'
    assert 'secret' not in text and 'model' not in text
    assert employee_activity({'product_phase': 'brief'})[0] == 'plan'


def test_announcements_keep_repeated_work_after_intervening_actions():
    async def run():
        seen = []
        async def emit(text):
            seen.append(text)
        bind_status(emit)
        await announce_tool('python_run', {})
        await announce_tool('python_run', {})  # duplicate announce at client and dispatcher
        assert len(seen) == 1
        await announce_tool('workspace_edit', {'path': 'report.py'})
        await announce_tool('python_run', {})  # a real rerun after an edit
        assert len(seen) == 3
        assert seen[-1].count('[work]') == 2
        await announce_tool('some_future_internal_tool', {'token': 'hidden'})
        assert 'some_future_internal_tool' not in seen[-1]
        assert 'hidden' not in seen[-1]
        await push_status('search', 'пример запроса')
        await push_status('search', 'ищу в интернете')
        assert not seen[-1].endswith('ищу в интернете')
    asyncio.run(run())


def test_director_emits_the_stage_without_changing_fallback_text():
    from director_router import _update_status
    async def run():
        seen = []
        async def emit(text):
            seen.append(text)
        bind_status(emit)
        await _update_status(None, 'Разбираю задачу — Определяю порядок работы', 'plan')
        assert seen[-1].startswith('[plan] Разбираю задачу')
    asyncio.run(run())


def test_cloud_swarm_event_never_exposes_internal_role_or_tool_name():
    from app.services.desktop_swarm import SwarmBoard
    from app.services.desktop_context import desktop_capabilities
    async def run():
        seen = []
        async def emit(text):
            seen.append(text)
        bind_status(emit)
        token = desktop_capabilities.set(set())
        try:
            board = SwarmBoard([])
            board.agents['one'] = {'id': 'one', 'role': 'swarm_read internal-role'}
            for state in ('working', 'done', 'error'):
                await board.event('one', state)
            assert seen
            assert not any('swarm_' in text or 'internal-role' in text for text in seen)
        finally:
            desktop_capabilities.reset(token)
    asyncio.run(run())
