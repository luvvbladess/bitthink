import asyncio
import time
from io import BytesIO
from uuid import uuid4
import zipfile
from types import SimpleNamespace
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.auth import get_current_user
from app.db.engine import SyncSessionLocal
from app.db.models import ComputerTask, ComputerHook, User
from app.core.repository import repo
from app.services import computer_tasks as tasks
from app.services.skill_packages import import_package, read_resource, export_package, parse_package


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


def test_account_isolation_and_task_controls(account):
    email, _ = account
    client = TestClient(app)
    response = client.post('/computer/tasks', json={'prompt': 'Проверь новые объявления', 'start_at': int(time.time()) + 100})
    assert response.status_code == 200
    row = response.json()
    assert row['status'] == 'scheduled'
    assert tasks.get_task('someone-else@example.com', row['id']) is None
    assert client.post('/computer/tasks', json={'prompt': 'test', 'interval_seconds': 1}).status_code == 400
    assert client.post(f"/computer/tasks/{row['id']}/pause").json()['status'] == 'paused'
    assert client.post(f"/computer/tasks/{row['id']}/resume").json()['resume_history'] is True
    tasks.control(email, row['id'], 'cancel')


def test_claim_once_and_expired_worker_needs_review(account):
    email, _ = account
    row = tasks.create_task(email, 'Проверить источники')
    claimed = tasks.claim()
    assert claimed['id'] == row['id']
    assert tasks.claim() is None
    with SyncSessionLocal() as session:
        session.get(ComputerTask, row['id']).lease_until = int(time.time()) - 1
        session.commit()
    assert tasks.claim() is None
    state = tasks.get_task(email, row['id'])
    assert state['status'] == 'interrupted' and not state['enabled']


def test_recurrence_and_journal_are_persistent(account):
    email, _ = account
    row = tasks.create_task(email, 'Сводка новостей', interval=86400)
    assert tasks.claim()['id'] == row['id']
    tasks.event(row['id'], 'before_tool', 'browse_page')
    tasks.finish(row['id'])
    state = tasks.get_task(email, row['id'])
    assert state['status'] == 'scheduled' and state['next_run_at'] >= int(time.time()) + 86399
    assert tasks.events(email, row['id'])[0]['detail'] == 'browse_page'
    tasks.control(email, row['id'], 'cancel')


def test_worker_uses_cloud_context_and_existing_chat_pipeline(account, monkeypatch):
    email, _ = account
    observed = []
    async def chat(user, content, cid, *args, **kwargs):
        from app.services.computer_context import computer_task_id
        observed.append((user, cid, computer_task_id.get()))
    monkeypatch.setattr('app.services.chat_service.run_chat', chat)
    row = tasks.create_task(email, 'Сравни предложения')
    claimed = tasks.claim()
    asyncio.run(tasks.ComputerWorker().run(claimed))
    result = tasks.get_task(email, row['id'])
    assert result['status'] == 'completed'
    assert observed == [(email, result['conversation_id'], row['id'])]


def test_declarative_hook_prevents_execution(account, monkeypatch):
    _, uid = account
    from computer_tools import run_computer_tool
    from app.services.computer_hooks import task_instructions
    with SyncSessionLocal() as session:
        session.add(ComputerHook(user_id=uid, name='No send', event='before_tool', action='deny', value='gmail_send', enabled=True))
        session.add(ComputerHook(user_id=uid, name='Report', event='before_task', action='instruction', value='В конце укажи источники', enabled=True))
        session.commit()
    async def forbidden(*args):
        raise AssertionError('Blocked tool was executed')
    monkeypatch.setattr('computer_tools._run_computer_tool', forbidden)
    assert 'запрещён' in asyncio.run(run_computer_tool('gmail_send', {}, uid))
    assert 'источники' in task_instructions(uid)
    assert 'источники' not in task_instructions(uid + 1)


def package(name):
    out = BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr('SKILL.md', f'---\nname: {name}\ndescription: Проверка источников для отчёта\n---\nСравни данные и приведи источники результатов.')
        archive.writestr('references/guide.md', 'Сверь факты с первичными документами.')
    return out.getvalue()


def test_portable_skill_preserves_resources_and_owner(account):
    _, uid = account
    name = 'verify_' + uuid4().hex[:8]
    imported = import_package(uid, package(name), 'test.zip')
    assert imported['resource_count'] == 1
    assert read_resource(uid + 1, name, 'references/guide.md') is None
    assert b'SKILL.md' in export_package(uid, name)
    assert read_resource(uid, name, 'references/guide.md').decode().startswith('Сверь')
    with pytest.raises(ValueError):
        import_package(uid, package(name), 'test.zip')
    out = BytesIO()
    with zipfile.ZipFile(out, 'w') as archive:
        archive.writestr('../SKILL.md', 'bad')
    with pytest.raises(ValueError):
        parse_package(out.getvalue(), 'unsafe.zip')


def test_mcp_tools_are_owner_allowlisted(monkeypatch):
    from app.services import mcp_client
    called = []
    class Session:
        async def call_tool(self, name, arguments):
            called.append(name)
            return SimpleNamespace(model_dump=lambda **kwargs: {'content': [{'type': 'text', 'text': 'found TOKEN-VALUE'}]})
    @asynccontextmanager
    async def fake_session(uid, cid):
        assert uid == 123 and cid == 4
        yield Session(), {'allowed_tools': ['search']}
    monkeypatch.setattr(mcp_client, 'session_for', fake_session)
    monkeypatch.setattr(mcp_client.connectors, 'secret_values', lambda uid: ['TOKEN-VALUE'])
    assert 'TOKEN-VALUE' not in asyncio.run(mcp_client.call(123, 4, 'search', {}))
    with pytest.raises(ValueError):
        asyncio.run(mcp_client.call(123, 4, 'delete', {}))
    assert called == ['search']


def test_mcp_rejects_private_and_embedded_credentials():
    from app.services.mcp_client import validate_endpoint
    for url in ['http://example.com/mcp', 'https://127.0.0.1/mcp', 'https://user:pass@example.com/mcp', 'https://example.com:8443/mcp']:
        with pytest.raises(ValueError):
            validate_endpoint(url)


def test_stale_worker_cannot_finish_or_modify_resumed_task(account):
    email, _ = account
    row = tasks.create_task(email, 'Повторить исследование')
    first = tasks.claim()
    tasks.control(email, row['id'], 'pause')
    tasks.control(email, row['id'], 'resume')
    second = tasks.claim()
    assert second['run_number'] > first['run_number']
    tasks.progress(row['id'], run_number=first['run_number'], progress='stale')
    tasks.finish(row['id'], run_number=first['run_number'])
    current = tasks.get_task(email, row['id'])
    assert current['status'] == 'running' and current['progress'] != 'stale'
    tasks.finish(row['id'], run_number=second['run_number'])
    restarted = tasks.control(email, row['id'], 'resume')
    assert restarted['resume_history'] is False
    tasks.control(email, row['id'], 'cancel')


def test_mcp_discovery_reads_pages(monkeypatch):
    from app.services import mcp_client
    cursors = []
    class Session:
        async def list_tools(self, cursor=None):
            cursors.append(cursor)
            return SimpleNamespace(tools=[SimpleNamespace(name='first' if cursor is None else 'second', description='read', inputSchema={'type':'object'})], nextCursor='page2' if cursor is None else None)
    @asynccontextmanager
    async def fake_session(uid, cid):
        yield Session(), {'allowed_tools':['second']}
    monkeypatch.setattr(mcp_client, 'session_for', fake_session)
    result = asyncio.run(mcp_client.discover(1, 2))
    assert cursors == [None, 'page2']
    assert result['tools'][1]['enabled'] is True


def test_mcp_official_sdk_handshake_and_call(monkeypatch):
    import json
    import httpx
    import mcp.client.streamable_http  # Resolve SDK annotations before replacing the HTTP client factory.
    from app.services import mcp_client
    methods = []
    original_client = httpx.AsyncClient
    async def respond(request):
        assert str(request.url) == 'https://mcp.example.com/mcp'
        assert request.headers['authorization'] == 'Bearer SDK-SECRET'
        if request.method == 'GET':
            return httpx.Response(405)
        if request.method == 'DELETE':
            return httpx.Response(204)
        message = json.loads(request.content)
        methods.append(message['method'])
        if 'id' not in message:
            return httpx.Response(202)
        if message['method'] == 'initialize':
            result = {'protocolVersion': message['params']['protocolVersion'], 'capabilities': {'tools': {}}, 'serverInfo': {'name':'fixture','version':'1'}}
        elif message['method'] == 'tools/list':
            result = {'tools':[{'name':'search','description':'fixture search','inputSchema':{'type':'object','properties':{}}}]}
        elif message['method'] == 'tools/call':
            result = {'content':[{'type':'text','text':'Found product with SDK-SECRET'}], 'isError':False}
        else:
            raise AssertionError(message['method'])
        return httpx.Response(200, json={'jsonrpc':'2.0','id':message['id'],'result':result}, headers={'Mcp-Session-Id':'fixture-session'})
    def factory(**kwargs):
        return original_client(transport=httpx.MockTransport(respond), **kwargs)
    monkeypatch.setattr(mcp_client.httpx, 'AsyncClient', factory)
    monkeypatch.setattr(mcp_client, 'validate_endpoint', lambda value:value)
    monkeypatch.setattr(mcp_client.connectors, 'get_secret', lambda uid,cid:(SimpleNamespace(type='mcp'),{'url':'https://mcp.example.com/mcp','token':'SDK-SECRET','allowed_tools':['search']}))
    monkeypatch.setattr(mcp_client.connectors, 'secret_values', lambda uid:['SDK-SECRET'])
    found = asyncio.run(mcp_client.discover(123,4))
    output = asyncio.run(mcp_client.call(123,4,'search',{}))
    assert found['tools'][0]['enabled'] is True
    assert 'SDK-SECRET' not in output and 'Found product' in output
    assert methods.count('initialize') == 2
    assert 'notifications/initialized' in methods and 'tools/list' in methods and 'tools/call' in methods
