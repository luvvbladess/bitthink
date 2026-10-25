"""Behavioral coverage for durable execution, isolation and migration-only boot."""
import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, event, select, update
from app.db.engine import SyncSessionLocal, sync_engine
from app.db.models import User
from app.db.generation_models import Generation, GenerationEvent, WorkerHeartbeat
from app.services import generation_store as store
from app.services.generation_hub import GenerationHub, LiveJob
from app.services.durable_hub import persistent_hub
from app.auth import create_access_token_for_user


@pytest.fixture
def account():
    suffix = uuid.uuid4().hex
    email = f'architecture-{suffix}@example.com'
    with SyncSessionLocal.begin() as session:
        session.add(User(email=email, password_hash='test-only', bot_user_id=int(suffix[:12], 16)))
    yield email
    with SyncSessionLocal.begin() as session:
        session.execute(delete(GenerationEvent).where(GenerationEvent.user_email == email))
        session.execute(delete(Generation).where(Generation.user_email == email))
        session.execute(delete(User).where(User.email == email))


def test_queue_survives_new_hub_and_claim_is_exclusive(account):
    job = store.reserve(account, 'chat', 'message', {'content': '138'})
    other_process = persistent_hub(GenerationHub, LiveJob)
    assert other_process.snapshots(account)[0]['user_text'] == '138'
    assert store.claim('worker-a')['id'] == job
    assert store.claim('worker-b') is None
    with pytest.raises(RuntimeError):
        store.reserve(account, 'chat', 'message', {'content': 'duplicate'})


def test_limit_covers_queued_jobs_not_only_running_tasks(account):
    for index in range(4):
        store.reserve(account, str(index), 'message', {'content': 'test'})
    with pytest.raises(RuntimeError, match='Слишком много'):
        store.reserve(account, 'fifth', 'message', {'content': 'test'})


def test_expired_run_is_interrupted_and_never_replayed(account):
    job = store.reserve(account, 'chat', 'message', {'content': 'external action'})
    store.claim('dead-worker')
    store.emit(account, 'dead-worker', {'type': 'chunk', 'payload': {'conversation_id': 'chat', 'text': 'partial'}}, job)
    with SyncSessionLocal.begin() as session:
        session.execute(update(Generation).where(Generation.id == job).values(lease_until=0))
    store.recover('maintenance')
    assert store.claim('replacement') is None
    snapshot = store.subscription(account)[0][0]
    assert snapshot['text'] == 'partial' and snapshot['thinking'] is False
    assert snapshot['error'] == store.INTERRUPTED
    with pytest.raises(RuntimeError, match='lease'):
        store.emit(account, 'dead-worker', {'type': 'chunk', 'payload': {'text': 'late'}}, job)
    store.reserve(account, 'chat', 'message', {'content': 'explicit retry'})
    assert len(store.subscription(account)[0]) == 1
    assert store.subscription(account)[0][0]['user_text'] == 'explicit retry'


def test_cancel_is_account_scoped_and_before_execution_costs_no_call(account, monkeypatch):
    from app.workers import generations as worker
    job = store.reserve(account, 'chat', 'message', {'content': 'never call provider'})
    assert not store.cancel('other@example.com', 'chat')
    assert store.cancel(account, 'chat')
    row = store.claim(worker.hub.publisher)
    async def forbidden(*args, **kwargs):
        raise AssertionError('cancelled job invoked provider')
    monkeypatch.setattr(worker, 'run_chat', forbidden)
    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            await worker.execute(row)
    asyncio.run(scenario())
    with SyncSessionLocal() as session:
        assert session.get(Generation, job).status == 'stopped'


class Socket:
    def __init__(self):
        self.sent = []
    async def send_json(self, message):
        self.sent.append(message)


async def until(predicate):
    for _ in range(50):
        if predicate():
            return
        await asyncio.sleep(.05)
    raise AssertionError('Event was not delivered')


def test_web_restart_does_not_stop_worker_and_reconnect_does_not_duplicate_chunks(account, monkeypatch):
    from app.workers import generations as worker
    store.reserve(account, 'chat', 'message', {'content': 'question'})
    row = store.claim(worker.hub.publisher)
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        async def fake(user, content, cid, **callbacks):
            assert (user, content, cid) == (account, 'question', 'chat')
            await callbacks['send_chunk']('first ')
            started.set()
            await release.wait()
            await callbacks['send_chunk']('second')
        monkeypatch.setattr(worker, 'run_chat', fake)
        api = persistent_hub(GenerationHub, LiveJob)
        await api.start()
        old_socket = Socket()
        await api.subscribe(account, old_socket)
        task = asyncio.create_task(worker.execute(row))
        await started.wait()
        await until(lambda: any(message['type'] == 'chunk' for message in old_socket.sent))
        await api.stop()  # simulates the web process disappearing
        assert not task.done() and store.running(account, 'chat')
        replacement = persistent_hub(GenerationHub, LiveJob)
        new_socket = Socket()
        initial = await replacement.subscribe(account, new_socket)
        assert initial[0]['text'] == 'first '
        await replacement.start()
        release.set()
        await task
        await until(lambda: any(message['type'] == 'done' for message in new_socket.sent))
        assert [message['payload']['text'] for message in new_socket.sent if message['type'] == 'chunk'] == ['second']
        await replacement.stop()
    asyncio.run(scenario())


def test_events_never_reach_another_account(account):
    store.reserve(account, 'chat', 'external', owner='owner')
    store.emit(account, 'owner', {'type': 'chunk', 'payload': {'conversation_id': 'chat', 'text': 'private'}})
    assert store.events(0, ['other@example.com']) == []
    assert store.subscription('other@example.com')[0] == []


def test_templates_and_custom_prompts_do_not_go_stale_in_another_process(account):
    from app.core.repository import repo
    from app.bot_core.db_conversations import DatabaseConversationManager
    uid = repo._bot_id(account)
    api, worker = DatabaseConversationManager(), DatabaseConversationManager()
    api.set_base_template(uid, b'first', 'first.docx')
    assert worker.get_base_template(uid) == b'first'
    api.set_base_template(uid, b'second', 'second.docx')
    assert worker.get_base_template(uid) == b'second'
    assert worker.get_base_template_name(uid) == 'second.docx'
    api.clear_base_template(uid)
    assert worker.get_base_template(uid) is None
    first = api.add_custom_prompt(uid, 'first instruction')
    second = api.add_custom_prompt(uid, 'second instruction')
    api.set_active_custom_prompt(uid, first)
    assert worker.get_active_custom_prompt(uid) == 'first instruction'
    worker.set_active_custom_prompt(uid, second)
    assert api.get_active_custom_prompt(uid) == 'second instruction'
    worker.set_active_custom_prompt(uid, None)
    assert api.get_active_custom_prompt(uid) is None
    api.delete_custom_prompt(uid, first)
    api.delete_custom_prompt(uid, second)


def test_worker_keeps_actionable_quota_errors(account, monkeypatch):
    from app.workers import generations as worker
    from app.billing.quota import QuotaError
    store.reserve(account, 'chat', 'message', {'content': 'test'})
    async def blocked(*args, **kwargs):
        raise QuotaError('Лимит токенов исчерпан. Дождитесь обновления лимита.', 'tokens')
    monkeypatch.setattr(worker, 'run_chat', blocked)
    asyncio.run(worker.execute(store.claim(worker.hub.publisher)))
    errors = [message for _, _, message in store.events(0, [account]) if message['type'] == 'error']
    assert errors[0]['payload']['message'].startswith('Лимит токенов исчерпан')


@pytest.mark.parametrize('payload', [[], {'type': 'auth', 'payload': ['invalid']}])
def test_malformed_auth_closes_without_starting_a_generation(payload):
    from app.main import create_app
    from starlette.websockets import WebSocketDisconnect
    with TestClient(create_app()) as client:
        with client.websocket_connect('/chat/ws') as socket:
            socket.send_json(payload)
            with pytest.raises(WebSocketDisconnect) as failure:
                socket.receive_json()
            assert failure.value.code == 1008


def test_queued_generation_keeps_the_submitted_model_and_resets_context(account, monkeypatch):
    from app.workers import generations as worker
    from app.core.repository import repo
    from app.bot_core.db_conversations import DatabaseConversationManager
    manager = DatabaseConversationManager()
    uid = repo._bot_id(account)
    manager.set_user_model(uid, 'gpt-6-luna')
    captured = asyncio.run(repo.capture_generation_preferences(account))
    store.reserve(account, 'chat', 'message', {'content': 'test', 'preferences': captured})
    manager.set_user_model(uid, 'gpt-6-sol')
    observed = []
    async def fake(*args, **kwargs):
        observed.append(manager.get_user_model(uid))
    monkeypatch.setattr(worker, 'run_chat', fake)
    asyncio.run(worker.execute(store.claim(worker.hub.publisher)))
    assert observed == ['gpt-6-luna']
    assert manager.get_user_model(uid) == 'gpt-6-sol'


def test_background_reply_does_not_change_the_selected_conversation(account, monkeypatch):
    from app.services import chat_service
    from app.core.repository import repo
    from app.bot_core.db_conversations import DatabaseConversationManager
    first = asyncio.run(repo.create_conversation(account, 'First'))['id']
    selected = asyncio.run(repo.create_conversation(account, 'Selected'))['id']
    async def fake(*args, **kwargs):
        pass
    monkeypatch.setattr(chat_service, '_generate_and_send', fake)
    async def scenario():
        await chat_service.run_chat(account, 'background reply', first, fake, fake, fake)
    asyncio.run(scenario())
    manager = DatabaseConversationManager()
    assert manager.get_active_conversation(repo._bot_id(account)).id == selected
    manager.delete_conversation(repo._bot_id(account), first)
    manager.delete_conversation(repo._bot_id(account), selected)


def test_schema_boot_is_read_only_and_websocket_enqueues_without_executing(account):
    from app.main import create_app
    statements = []
    def observe(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(('CREATE ', 'ALTER ', 'DROP ')):
            statements.append(statement)
    event.listen(sync_engine, 'before_cursor_execute', observe)
    try:
        with TestClient(create_app()) as client:
            token = create_access_token_for_user(account, 'user')
            with client.websocket_connect('/chat/ws') as socket:
                socket.send_json({'type': 'auth', 'payload': {'token': token}})
                assert socket.receive_json()['type'] == 'jobs'
                socket.send_json({'type': 'message', 'payload': {'conversation_id': 'test-chat', 'content': 'hello'}})
                assert socket.receive_json()['type'] == 'thinking'
                assert store.running(account, 'test-chat')
            assert client.get('/health').json() == {'status': 'ok'}
        assert statements == []
    finally:
        event.remove(sync_engine, 'before_cursor_execute', observe)


def test_diagnostics_are_authenticated_and_reject_private_content(account, caplog):
    from app.main import create_app
    payload = {'report_id': str(uuid.uuid4()), 'category': 'render', 'route': '/chat',
        'build': 'index-abc123.js', 'frames': [{'file': 'ChatPage-abc.js', 'line': 1, 'column': 20}]}
    with TestClient(create_app()) as client:
        assert client.post('/diagnostics/client-error', json=payload).status_code == 401
        headers = {'Authorization': 'Bearer ' + create_access_token_for_user(account, 'user')}
        assert client.post('/diagnostics/client-error', json={**payload, 'message': 'PRIVATE_TEXT'}, headers=headers).status_code == 422
        assert client.post('/diagnostics/client-error', json={**payload, 'route': '/chat?token=PRIVATE_TEXT'}, headers=headers).status_code == 422
        assert client.post('/diagnostics/client-error', json=payload, headers=headers).status_code == 200
        assert payload['report_id'] in caplog.text
        assert account not in caplog.text and 'PRIVATE_TEXT' not in caplog.text
        for _ in range(9):
            assert client.post('/diagnostics/client-error', json=payload, headers=headers).status_code == 200
        assert client.post('/diagnostics/client-error', json=payload, headers=headers).status_code == 429


def test_fresh_database_migrates_without_importing_future_orm_schema(tmp_path):
    target = tmp_path / 'migrations.db'
    environment = {**os.environ, 'DATABASE_URL': 'sqlite+aiosqlite:///' + target.as_posix()}
    backend = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=backend, env=environment, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    result = subprocess.run([sys.executable, '-c', 'from app.main import _validate_schema; _validate_schema()'], cwd=backend, env=environment, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
