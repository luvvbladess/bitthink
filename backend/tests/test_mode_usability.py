"""Mode intent must survive queues, other tabs and preference changes."""
import asyncio
import json
import time
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update
from app.auth import create_access_token_for_user
from app.core.repository import repo
from app.db.engine import SyncSessionLocal
from app.db.models import User, Subscription, Conversation, ComputerTask, ComputerEvent
from app.db.generation_models import Generation, GenerationEvent
from app.db.experience_models import ChatSubmission
from app.services import generation_store as store


@pytest.fixture
def account():
    email = 'modes-' + uuid.uuid4().hex + '@example.invalid'
    uid = repo._bot_id(email)
    with SyncSessionLocal.begin() as session:session.add(User(email=email, bot_user_id=uid, password_hash='unusable-test'))
    yield email, uid
    with SyncSessionLocal.begin() as session:
        tasks = select(ComputerTask.id).where(ComputerTask.user_email == email)
        session.execute(delete(ComputerEvent).where(ComputerEvent.task_id.in_(tasks)))
        session.execute(delete(ComputerTask).where(ComputerTask.user_email == email))
        for model in [ChatSubmission, GenerationEvent, Generation]:session.execute(delete(model).where(model.user_email == email))
        for row in session.scalars(select(Conversation).where(Conversation.user_id == uid)):session.delete(row)
        session.execute(delete(Subscription).where(Subscription.user_id == uid))
        session.execute(delete(User).where(User.email == email))


def test_queued_image_tools_keep_quality_that_was_submitted(account, monkeypatch):
    from app.workers import generations
    from app.bot_core.db_conversations import DatabaseConversationManager
    email, uid = account; manager = DatabaseConversationManager()
    manager.set_user_model(uid, 'gpt-6-luna'); manager.set_user_image_quality(uid, 'low')
    captured = asyncio.run(repo.capture_generation_preferences(email))
    store.reserve(email, 'mode-chat', 'message', {'content': 'test', 'preferences': captured})
    manager.set_user_image_quality(uid, 'high')
    observed=[]
    async def fake(*args, **kwargs):observed.append(manager.get_user_image_quality(uid))
    monkeypatch.setattr(generations, 'run_chat', fake)
    asyncio.run(generations.execute(store.claim(generations.hub.publisher)))
    assert observed == ['low']
    assert manager.get_user_image_quality(uid) == 'high'


def test_orchestrator_does_not_turn_into_studio_when_account_mode_changes(account, monkeypatch):
    from app.services import computer_tasks
    from app.bot_core.db_conversations import DatabaseConversationManager
    email, uid = account; manager = DatabaseConversationManager()
    manager.set_subscription_tier(uid, 'pro', 30, from_today=True)
    manager.set_user_model(uid, 'director'); manager.set_user_image_quality(uid, 'low')
    row = computer_tasks.create_task(email, 'Check a synthetic proposal')
    with SyncSessionLocal.begin() as session:
        session.execute(update(ComputerTask).where(ComputerTask.id == row['id']).values(status='running', run_number=1, lease_until=int(time.time())+300))
    manager.set_user_model(uid, 'studio'); manager.set_user_image_quality(uid, 'high')
    observed=[]
    async def fake(*args, **kwargs):observed.append((manager.get_user_model(uid), manager.get_user_image_quality(uid)))
    monkeypatch.setattr('app.services.chat_service.run_chat', fake)
    asyncio.run(computer_tasks.ComputerWorker().run({**computer_tasks.get_task(email, row['id']), 'user_email':email}))
    assert observed == [('director', 'low')]
    assert computer_tasks.get_task(email, row['id'])['status'] == 'completed'
    assert manager.get_user_model(uid) == 'studio'
    assert manager.get_user_image_quality(uid) == 'high'
    assert all(item['kind'] != 'preferences' for item in computer_tasks.events(email, row['id']))


def test_expired_plan_does_not_advertise_or_select_premium_modes(account, monkeypatch):
    from app.main import create_app
    email, _ = account
    async def expired(_):return {'tier':'proplus', 'expires_at':int(time.time())-60}
    monkeypatch.setattr(repo, 'get_subscription', expired)
    headers={'Authorization':'Bearer '+create_access_token_for_user(email, 'user')}
    with TestClient(create_app()) as client:
        response=client.get('/models',headers=headers);assert response.status_code==200
        data=response.json()
        assert data['astraAvailable'] is False and data['computerAvailable'] is False
        assert data['researchModel'] is None and data['searchAvailable'] is True
        assert client.post('/models/select',json={'model':'gpt-6-astra'},headers=headers).status_code==403


def test_explicit_mode_is_bound_to_the_message_not_to_another_tab(account):
    from app.main import create_app
    email, uid = account
    asyncio.run(repo.set_user_model(email, 'auto'))
    with TestClient(create_app()) as client:
        with client.websocket_connect('/chat/ws') as socket:
            socket.send_json({'type':'auth','payload':{'token':create_access_token_for_user(email, 'user')}})
            assert socket.receive_json()['type']=='jobs'
            socket.send_json({'type':'message','payload':{'conversation_id':'test-mode','content':'hello','request_id':uuid.uuid4().hex,'model':'gpt-5.6-luna'}})
            receipt=socket.receive_json();assert receipt['type']=='accepted'
    with SyncSessionLocal() as session:
        row=session.scalar(select(Generation).where(Generation.user_email==email))
        assert json.loads(row.request)['preferences']['selected_model']=='gpt-6-luna'
    assert asyncio.run(repo.get_user_model(email))=='auto'


@pytest.mark.parametrize('model',['gpt-6-astra','not-a-model',123])
def test_forged_or_locked_mode_is_rejected_without_a_job(account, model):
    from app.main import create_app
    email, _ = account; request_id=uuid.uuid4().hex
    with TestClient(create_app()) as client:
        with client.websocket_connect('/chat/ws') as socket:
            socket.send_json({'type':'auth','payload':{'token':create_access_token_for_user(email, 'user')}})
            socket.receive_json()
            socket.send_json({'type':'message','payload':{'conversation_id':'test-mode','content':'hello','request_id':request_id,'model':model}})
            result=socket.receive_json()
            assert result['type']=='error' and result['payload']['request_id']==request_id
    assert store.count(email)==0


@pytest.mark.parametrize('data',[{'prompt':123},{'prompt':'draw','conversation_id':123},
    {'prompt':'draw','source_urls':'not-a-list'}, {'prompt':'draw','source_urls':['/uploads/test.png']*9}])
def test_invalid_image_requests_fail_before_quota_or_provider(account, monkeypatch, data):
    from app.main import create_app
    email, _ = account
    async def forbidden(*args):raise AssertionError('Malformed request reached the provider gate')
    monkeypatch.setattr('app.api.media._gate_image', forbidden)
    with TestClient(create_app()) as client:
        response=client.post('/media/images/generate',json=data,headers={'Authorization':'Bearer '+create_access_token_for_user(email, 'user')})
        assert response.status_code==400


def test_image_stop_reaches_the_provider_task_through_the_durable_flag(account):
    from fastapi import HTTPException
    from app.api.media import _await_image_operation
    from app.services.generation_hub import hub
    email, _ = account
    store.reserve(email, 'image-mode', owner=hub.publisher)
    stopped=[]
    async def provider():
        try:await asyncio.sleep(60)
        finally:stopped.append(True)
    async def scenario():
        task=asyncio.create_task(_await_image_operation(provider(), email, 'image-mode'))
        await asyncio.sleep(.01)
        await asyncio.to_thread(store.cancel, email, 'image-mode')
        with pytest.raises(HTTPException) as error:await asyncio.wait_for(task, 2)
        assert error.value.status_code==409
    asyncio.run(scenario())
    assert stopped==[True]


def test_more_than_eight_image_uploads_are_rejected_instead_of_silently_dropped(account, monkeypatch):
    from app.main import create_app
    email, uid = account
    async def gate(*args):return uid
    monkeypatch.setattr('app.api.media._gate_image', gate)
    uploads=[('files', (f'{index}.png', b'synthetic', 'image/png')) for index in range(9)]
    with TestClient(create_app()) as client:
        result=client.post('/media/images/edit',data={'prompt':'edit'},files=uploads,
            headers={'Authorization':'Bearer '+create_access_token_for_user(email, 'user')})
        assert result.status_code==400 and '8' in result.json()['detail']


def test_trashing_a_running_image_request_cancels_it_without_a_server_error(account, monkeypatch):
    from app.api.media import generate_image
    from app.domains.conversations import trash
    from fastapi import HTTPException
    email, uid = account
    cid=asyncio.run(repo.create_conversation(email, 'Synthetic image'))['id']
    async def gate(*args):return uid
    monkeypatch.setattr('app.api.media._gate_image', gate)
    async def scenario():
        started=asyncio.Event()
        async def provider(*args, **kwargs):
            started.set();await asyncio.sleep(60)
        monkeypatch.setattr('openai_client.generate_image', provider)
        task=asyncio.create_task(generate_image({'prompt':'synthetic image','conversation_id':cid}, email))
        await asyncio.wait_for(started.wait(), 2)
        await asyncio.to_thread(trash, uid, cid)
        with pytest.raises(HTTPException) as error:await asyncio.wait_for(task, 2)
        assert error.value.status_code==409
    asyncio.run(scenario())
    assert store.count(email)==0
