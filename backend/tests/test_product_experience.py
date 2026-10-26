"""User-facing contracts: bounded reads, recovery, delivery, privacy and access."""
import asyncio
import json
import time
import uuid
import pytest
from sqlalchemy import delete, event, select, update
from fastapi.testclient import TestClient
from app.auth import create_access_token_for_user
from app.core.repository import repo
from app.db.engine import SyncSessionLocal, sync_engine
from app.db.models import User, Conversation, ConversationMember, Message, Document, Subscription
from app.db.generation_models import Generation, GenerationEvent
from app.db.experience_models import ChatSubmission, ExperienceMetric
from app.domains import conversations as library
from app.services import generation_store as store


@pytest.fixture
def people():
    emails = ['experience-' + uuid.uuid4().hex + '@example.invalid' for _ in range(2)]
    ids = [repo._bot_id(email) for email in emails]
    with SyncSessionLocal.begin() as session:
        for email, uid in zip(emails, ids):session.add(User(email=email, bot_user_id=uid, password_hash='test-only'))
    yield emails, ids
    with SyncSessionLocal.begin() as session:
        for model in [ChatSubmission, GenerationEvent, Generation]:session.execute(delete(model).where(model.user_email.in_(emails)))
        for conv in session.scalars(select(Conversation).where(Conversation.user_id.in_(ids))):session.delete(conv)
        session.execute(delete(Subscription).where(Subscription.user_id.in_(ids)))
        session.execute(delete(User).where(User.email.in_(emails)))


def make_chat(email, title='Proposal'):
    return asyncio.run(repo.create_conversation(email, title))['id']


def test_sidebar_reads_only_metadata_and_paginates(people):
    emails, ids = people
    chats = [make_chat(emails[0], str(i)) for i in range(4)]
    with SyncSessionLocal.begin() as session:
        session.add(Message(conversation_id=chats[0], role='user', content='PRIVATE_BODY' * 10000))
    statements = []
    def capture(conn, cursor, statement, *args):statements.append(statement)
    event.listen(sync_engine, 'before_cursor_execute', capture)
    try:
        first = library.summaries(ids[0], 2)
        second = library.summaries(ids[0], 2, 2)
    finally:event.remove(sync_engine, 'before_cursor_execute', capture)
    assert len(first) == len(second) == 2
    assert {r['id'] for r in first}.isdisjoint({r['id'] for r in second})
    assert not any('messages.content' in sql or 'documents.content' in sql for sql in statements)
    assert sum(item['message_count'] for item in first + second) == 1


def test_history_pages_preserve_absolute_indices_and_access(people):
    emails, ids = people
    cid = make_chat(emails[0])
    with SyncSessionLocal.begin() as session:
        session.add_all([Message(conversation_id=cid, role='user' if i % 2 == 0 else 'assistant', content=str(i)) for i in range(185)])
    page = library.history(ids[0], cid)
    assert len(page['items']) == 80 and page['offset'] == 105 and page['has_more']
    older = library.history(ids[0], cid, before=page['before'])
    assert len(older['items']) == 80 and older['offset'] == 25
    assert older['items'][-1]['content'] == '104'
    assert page['items'][0]['id'] == cid + '_105'
    found = library.history(ids[0], cid, around=older['items'][10]['message_id'])
    assert found['items'][0]['content'] == '35' and found['has_newer']
    with pytest.raises(PermissionError):library.history(ids[1], cid)


def test_full_text_search_finds_messages_and_filenames_but_never_other_accounts(people):
    emails, ids = people
    cid = make_chat(emails[0], 'General work')
    hidden = make_chat(emails[1], 'Competitor')
    with SyncSessionLocal.begin() as session:
        session.add_all([Message(conversation_id=cid, role='assistant', content='Условия поставки: предоплата тридцать процентов.'),
            Message(conversation_id=hidden, role='assistant', content='предоплата PRIVATE_OTHER_ACCOUNT')])
        session.add(Document(conversation_id=cid, filename='Спецификация-2026.txt', content='source'))
    hits = library.search(ids[0], 'предоплата')
    assert len(hits) == 1 and hits[0]['id'] == cid and hits[0]['message_id']
    assert library.search(ids[0], 'Спецификация')[0]['id'] == cid
    assert 'PRIVATE_OTHER_ACCOUNT' not in json.dumps(hits)
    assert library.search(ids[0], '%') == []


def test_trash_is_hidden_recoverable_and_owner_only(people):
    emails, ids = people
    cid = make_chat(emails[0])
    with SyncSessionLocal.begin() as session:session.add(ConversationMember(conversation_id=cid, user_id=ids[1]))
    assert not library.trash(ids[1], cid)
    assert library.trash(ids[0], cid)
    assert not library.summaries(ids[0]) and not library.summaries(ids[1])
    assert library.summaries(ids[0], trash=True)[0]['id'] == cid
    with pytest.raises(PermissionError):library.history(ids[1], cid)
    assert not library.trash(ids[1], cid, True)
    assert library.trash(ids[0], cid, True)
    assert library.summaries(ids[1])[0]['id'] == cid


def test_trash_stops_queued_work_and_preserves_project_binding(people):
    from app.services import project_memory
    emails, ids = people
    cid = make_chat(emails[0])
    project = project_memory.create(ids[0], 'Work')
    project_memory.attach(ids[0], cid, project['id'])
    job = store.reserve(emails[0], cid, 'message', {'content': 'work'})
    library.trash(ids[0], cid)
    with SyncSessionLocal() as session:assert session.get(Generation, job).cancel_requested
    assert not project_memory.list_projects(ids[0])[0]['chat_ids']
    library.trash(ids[0], cid, True)
    assert cid in project_memory.list_projects(ids[0])[0]['chat_ids']
    project_memory.delete_project(ids[0], project['id'])


def test_expired_trash_is_purged_without_deleting_active_chats(people):
    emails, ids = people
    cid = make_chat(emails[0]); active = make_chat(emails[0])
    library.trash(ids[0], cid)
    with SyncSessionLocal.begin() as session:session.execute(update(Conversation).where(Conversation.id == cid).values(deleted_at=int(time.time()) - 31 * 86400))
    assert not library.trash(ids[0], cid, True)
    library.purge_expired()
    with SyncSessionLocal() as session:
        assert session.get(Conversation, cid) is None
        assert session.get(Conversation, active) is not None


def test_message_receipt_survives_completion_and_rejects_key_reuse(people):
    emails, ids = people
    user = emails[0]; key = uuid.uuid4().hex
    original = store.reserve(user, 'chat', 'message', {'content': 'hello'}, request_id=key)
    assert store.reserve(user, 'chat', 'message', {'content': 'hello', 'preferences': {'model': 'different'}}, request_id=key) == original
    row = store.claim('receipt-worker'); assert row['id'] == original
    store.finish(user, 'chat', 'completed', original)
    assert store.reserve(user, 'chat', 'message', {'content': 'hello'}, request_id=key) == original
    assert store.count(user) == 0
    with pytest.raises(RuntimeError, match='идентификатор|Идентификатор'):store.reserve(user, 'chat', 'message', {'content': 'different'}, request_id=key)
    other = store.reserve(emails[1], 'chat', 'message', {'content': 'hello'}, request_id=key)
    assert other != original


def test_pending_conversation_receipt_is_stable(people):
    emails, _ = people
    key = uuid.uuid4().hex
    first = store.reserve(emails[0], None, 'message', {'content': 'hi'}, request_id=key)
    assert store.reserve(emails[0], None, 'message', {'content': 'hi'}, request_id=key) == first


def test_websocket_acknowledges_delivery_and_replay_without_new_job(people):
    from app.main import create_app
    emails, _ = people; email = emails[0]
    key = uuid.uuid4().hex
    with TestClient(create_app()) as client:
        with client.websocket_connect('/chat/ws') as ws:
            ws.send_json({'type': 'auth', 'payload': {'token': create_access_token_for_user(email, 'user')}})
            assert ws.receive_json()['type'] == 'jobs'
            frame = {'type': 'message', 'payload': {'conversation_id': 'chat', 'content': 'hello', 'request_id': key}}
            ws.send_json(frame); first = ws.receive_json()
            ws.send_json(frame); second = ws.receive_json()
            assert first['type'] == 'accepted' and first == second
            assert store.count(email) == 1


def test_performance_is_bounded_anonymous_and_admin_only(people):
    from app.main import create_app
    emails, _ = people
    headers = {'Authorization': 'Bearer ' + create_access_token_for_user(emails[0], 'user')}
    with TestClient(create_app()) as client:
        payload = {'metrics': [{'name': 'history_load', 'value': 120, 'device': 'mobile'}]}
        assert client.post('/diagnostics/performance', json=payload).status_code == 401
        assert client.post('/diagnostics/performance', json=payload, headers=headers).status_code == 200
        assert client.post('/diagnostics/performance', json={**payload, 'email': 'PRIVATE'}, headers=headers).status_code == 422
        assert client.get('/diagnostics/performance', headers=headers).status_code == 403
    with SyncSessionLocal() as session:
        rows = session.scalars(select(ExperienceMetric).where(ExperienceMetric.name == 'history_load')).all()
        assert rows and all(emails[0] not in row.id for row in rows)


def test_activity_is_account_scoped_and_terminal_tasks_are_visible(people):
    from app.domains.execution import activity, stop
    emails, _ = people
    cid = make_chat(emails[0], 'Release task')
    job = store.reserve(emails[0], cid, 'message', {'content': 'private task'})
    assert not activity(emails[1]) and not stop(emails[1], job)
    store.finish(emails[0], cid, 'completed', job)
    assert activity(emails[0])[0]['status'] == 'completed'
    assert activity(emails[0])[0]['prompt'] == 'Release task'
    assert not stop(emails[0], job)
