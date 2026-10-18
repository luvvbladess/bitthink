import asyncio
import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.auth import get_current_user
from app.core.repository import repo
from app.db.engine import SyncSessionLocal
from app.db.models import User
from app.services.run_protocol import RunRecord, current_run, public_url
from computer_skills.adaptations import registry, templates, read_builtin_resource
from computer_skills.loader import builtin_names, load_skill, match_skills
from computer_tools import run_computer_tool, CHAT_TOOL_NAMES, COMPUTER_TOOL_NAMES


@pytest.fixture
def account():
    email = uuid4().hex + '@example.com'
    uid = repo._bot_id(email)
    with SyncSessionLocal() as session:
        session.add(User(email=email, password_hash='test', role='user', bot_user_id=uid))
        session.commit()
    repo._manager.set_subscription_tier(uid, 'pro', 30, from_today=True)
    app.dependency_overrides[get_current_user] = lambda: email
    yield email, uid
    app.dependency_overrides.clear()


def test_catalog_is_complete_but_personal_rules_are_opt_in():
    rows = registry()
    assert len(rows) == 46
    assert len({r['source_name'] for r in rows.values()}) == 46
    assert len(templates()) == 8
    builtins = set(builtin_names())
    for name, row in rows.items():
        assert len(row['source_sha256']) == 64
        assert (name in builtins) == (row['adaptation'] == 'builtin')
        assert len(name) <= 32
    for template in templates():
        assert template['name'] not in match_skills(template['title'], limit=20)


@pytest.mark.parametrize('text,expected', [
    ('Подготовь PRD и дорожную карту продукта', 'wf_product'),
    ('Сделай сверку, потом каждый день присылай результат', 'wf_automations'),
    ('load_skill browser-use', 'wf_browser_workflow'),
    ('load_skill wf_search', 'wf_search'),
    ('Как начать пользоваться?', 'wf_onboarding'),
])
def test_adapted_domain_routing(text, expected):
    assert expected in match_skills(text, limit=3)


@pytest.mark.parametrize('text,expected', [
    ('https://ozon.ru/t/abc Сравни рации и отзывы', 'marketplaces'),
    ('Проверь чертёж по ЕСКД', 'eng_drawing'),
    ('План закупки компонентов для платы', 'marketplaces'),
    ('Сделай таблицу Excel', 'spreadsheet'),
])
def test_native_domain_skills_keep_precedence(text, expected):
    assert match_skills(text, limit=1) == [expected]


def test_narrow_triggers_do_not_inject_unrelated_workflows():
    assert match_skills('Привет, сколько будет два плюс два?') == []
    assert 'wf_onboarding' not in match_skills('Привет, я здесь впервые')
    assert 'wf_support' not in match_skills('Проверь баг в коде')
    assert 'wf_automations' not in match_skills('Сравни три рации')


def test_builtin_alias_and_disabled_resources(account):
    email, uid = account
    assert '# wf_browser_workflow' in load_skill('browser-use', uid)
    assert 'references/contract.md' in load_skill('wf_browser_workflow', uid)
    assert read_builtin_resource('browser-use', 'references/contract.md', uid)
    asyncio.run(repo.set_builtin_skill_enabled(email, 'wf_browser_workflow', False))
    assert 'выключен' in load_skill('browser-use', uid)
    assert read_builtin_resource('browser-use', 'references/contract.md', uid) is None
    assert 'wf_browser_workflow' not in match_skills('load_skill browser-use', user_id=uid)


@pytest.mark.parametrize('path', ['../../config.py', '/etc/passwd', 'C:/private', 'references\\contract.md'])
def test_resource_paths_cannot_escape_builtin_package(path):
    with pytest.raises(ValueError):
        read_builtin_resource('wf_search', path, None)
    assert '# wf_search' not in load_skill('../../wf_search')


def test_builtin_resource_pagination_and_shared_access(monkeypatch):
    import computer_skills.loader as loader
    monkeypatch.setattr(loader, 'turn_is_shared', lambda uid: True)
    text = read_builtin_resource('wf_search', 'references/contract.md', None).decode()
    output = asyncio.run(run_computer_tool('read_skill_resource', {'skill': 'wf_search', 'path': 'references/contract.md', 'offset': 100, 'limit': 200}, None))
    assert output.split('\n', 1)[1] == text[100:300]
    private = asyncio.run(run_computer_tool('read_skill_resource', {'skill': 'my_private', 'path': 'guide.md'}, 42))
    assert 'личной беседе' in private


def test_template_installation_preserves_account_isolation_and_no_overwrite(account):
    email, uid = account
    client = TestClient(app)
    items = client.get('/skills/templates').json()['items']
    assert len(items) == 8
    for template in items:
        row = client.post('/skills/templates/' + template['name'])
        assert row.status_code == 200, row.text
        assert row.json()['origin'] == 'custom' and row.json()['enabled']
    name = items[0]['name']
    assert client.post('/skills/templates/' + name).status_code == 400
    assert client.post('/skills/templates/not_known').status_code == 400
    from computer_skills.loader import catalog
    assert name in {row['name'] for row in catalog(uid)}
    assert name not in {row['name'] for row in catalog(uid + 1)}


def test_capabilities_reference_real_tools_and_honest_limits():
    data = json.loads(asyncio.run(run_computer_tool('get_capabilities', {}, None)))
    assert data['model_selection'] == 'automatic'
    for group in data['groups']:
        assert set(group['tools']) <= COMPUTER_TOOL_NAMES
    assert next(g for g in data['groups'] if g['id'] == 'voice')['status'] == 'requires_adapter'
    assert {'task_create', 'task_control'} <= COMPUTER_TOOL_NAMES
    assert not ({'task_create', 'task_control'} & CHAT_TOOL_NAMES)


def test_natural_language_task_tools_use_owner_and_existing_limits(account, monkeypatch):
    email, uid = account
    from app.services.task_tools import run_task_tool
    from app.services import computer_tasks
    row = json.loads(asyncio.run(run_task_tool('task_create', {'prompt': 'Проверь цену', 'start_at': int(time.time()) + 300}, uid)))
    try:
        assert row['status'] == 'scheduled'
        assert computer_tasks.get_task('another@example.com', row['id']) is None
        rows = json.loads(asyncio.run(run_task_tool('task_list', {}, uid)))
        assert row['id'] in {r['id'] for r in rows}
        paused = json.loads(asyncio.run(run_task_tool('task_control', {'task_id': row['id'], 'action': 'pause'}, uid)))
        assert paused['status'] == 'paused'
        assert 'пяти минут' in asyncio.run(run_task_tool('task_create', {'prompt': 'test', 'interval_seconds': 1}, uid))
        repo._manager.set_subscription_tier(uid, 'free', 30, from_today=True)
        assert 'Pro' in asyncio.run(run_task_tool('task_create', {'prompt': 'test'}, uid))
        monkeypatch.setattr('computer_skills.loader.turn_is_shared', lambda _: True)
        assert 'личной беседе' in asyncio.run(run_task_tool('task_control', {'task_id': row['id'], 'action': 'cancel'}, uid))
    finally:
        computer_tasks.control(email, row['id'], 'cancel')


def test_background_run_cannot_spawn_nested_tasks_or_mutate_its_schedule(account):
    from app.services.task_tools import run_task_tool
    from app.services.computer_context import computer_task_id
    token = computer_task_id.set('current-task')
    try:
        assert 'вложенные' in asyncio.run(run_task_tool('task_create', {'prompt': 'test'}, account[1]))
        assert 'собственное' in asyncio.run(run_task_tool('task_control', {'task_id': 'current-task', 'action': 'pause'}, account[1]))
    finally:
        computer_task_id.reset(token)


def test_parallel_retries_enroll_one_background_task_per_turn(account):
    from app.services.task_tools import run_task_tool
    from app.services import computer_tasks
    record = RunRecord()
    async def run():
        token = current_run.set(record)
        try:
            args = {'prompt': 'Проверь конкретную цену', 'start_at': int(time.time()) + 500}
            return await asyncio.gather(*(run_task_tool('task_create', args, account[1]) for _ in range(3)))
        finally:
            current_run.reset(token)
    results = [json.loads(row) for row in asyncio.run(run())]
    assert len({row['id'] for row in results}) == 1
    computer_tasks.control(account[0], results[0]['id'], 'cancel')


def test_evidence_distinguishes_page_snippet_error_and_review_texts():
    record = RunRecord(requires_sources=True)
    record.observe('browse_page', 'URL: https://example.com/a\nЗапрос: test\n\n' + 'Реальное содержание страницы. ' * 5 + 'Отзывы: 123')
    record.observe('browse_page', 'URL: https://example.com/b\n[Сайт закрыт, саму страницу открыть не удалось. Ниже то, что поиск знает по этой ссылке.]')
    record.observe('browse_page', 'URL: https://example.com/c\n[Ошибка загрузки страницы]')
    record.observe('browse_page', 'URL: https://example.com/d\n' + 'Реальные данные. ' * 5 + '\nТЕКСТЫ ОТЗЫВОВ (2): понравился звук')
    record.observe('browse_page', 'URL: https://example.com/e\nЗапрос: ' + 'длинный запрос ' * 20)
    assert [s['status'] for s in record.sources] == ['read', 'retrieved', 'failed', 'read', 'insufficient']
    assert [s['reviews'] for s in record.sources][:4] == ['unknown', 'unknown', 'unknown', 'read']
    assert not record.sources[1]['excerpt']
    assert not record.sources[2]['excerpt']


def test_evidence_never_rewrites_private_urls_and_keeps_json_valid():
    assert public_url('https://example.com/?token=private') == ''
    assert public_url('https://user:pass@example.com') == ''
    assert public_url('https://example.com/?sku=123&text=a%20b#fragment') == 'https://example.com/?sku=123&text=a%20b'
    record = RunRecord()
    for i in range(100):
        record.observe('browse_page', f'URL: https://example.com/{i}\n' + 'данные ' * 1000)
    data = json.loads(record.evidence_prompt().split('\n')[-1])
    assert len(data['sources']) == 24 and data['sources_omitted'] == 36
    assert len(record.tools) == 100


def test_actual_page_sources_survive_search_deduplication_and_limit():
    from handlers.core import _merge_sources
    snippets = [{'query': 'search result', 'summary': f'https://example.com/{i}\nSearch snippet'} for i in range(35)]
    record = RunRecord()
    record.observe('browse_page', 'URL: https://example.com/34\n' + 'Actual content ' * 10)
    record.observe('browse_page', 'URL: https://example.com/unread\n[Ошибка загрузки]')
    rows = _merge_sources(snippets, record.enrich_sources(snippets), limit=28)
    assert rows[0]['evidence_state'] == 'read'
    assert rows[0]['summary'].startswith('https://example.com/34\nActual content')
    assert rows[1]['evidence_state'] == 'failed'
    assert len(rows) == 28


def test_parallel_tool_observations_are_shared_and_turn_context_is_reset(monkeypatch):
    import director_router
    record = RunRecord()
    async def fake_run(*args):
        observed = current_run.get()
        assert observed is not record
        async def child(url):
            current_run.get().observe('browse_page', 'URL: ' + url + '\n' + 'read content ' * 10)
        await asyncio.gather(child('https://one.example'), child('https://two.example'))
        assert len(observed.sources) == 2
        raise RuntimeError('fixture failure')
    monkeypatch.setattr(director_router, '_run_director', fake_run)
    token = current_run.set(record)
    try:
        with pytest.raises(RuntimeError):
            asyncio.run(director_router.get_director_response([], 'test', 123, None))
        assert current_run.get() is record and record.sources == []
    finally:
        current_run.reset(token)
