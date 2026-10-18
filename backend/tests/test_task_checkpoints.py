import asyncio
import time
from uuid import uuid4
import pytest
from app.db.base import Base
from app.db.engine import SyncSessionLocal, sync_engine
from app.db.models import User, ComputerTask
from app.core.repository import repo
from app.services import computer_tasks as tasks, task_checkpoints as checkpoints
from app.services.computer_context import computer_task_id


@pytest.fixture
def run():
    Base.metadata.create_all(sync_engine)
    email = uuid4().hex + '@example.com'; uid = repo._bot_id(email)
    with SyncSessionLocal() as session:
        session.add(User(email=email, password_hash='test', bot_user_id=uid)); session.commit()
    row = tasks.create_task(email, 'Подготовить отчёт')
    with SyncSessionLocal() as session:
        task = session.get(ComputerTask, row['id']); task.status='running'; task.run_number=1; task.lease_until=int(time.time())+90; session.commit()
    a = computer_task_id.set(row['id']); b = checkpoints.task_run_number.set(1)
    group, _ = checkpoints.begin(row['id'], 1, False); c = checkpoints.logical_run.set(group)
    yield email, uid, row['id']
    checkpoints.logical_run.reset(c); checkpoints.task_run_number.reset(b); computer_task_id.reset(a)
    for task in tasks.list_tasks(email): tasks.control(email, task['id'], 'cancel')


def test_enrollment_retry_is_persistent_and_payload_checked(run):
    email, _, _ = run
    first = tasks.create_task(email, 'Мониторинг цены', idempotency_key='request-12345')
    assert tasks.create_task(email, 'Мониторинг цены', idempotency_key='request-12345')['id'] == first['id']
    with pytest.raises(ValueError): tasks.create_task(email, 'Другой запрос', idempotency_key='request-12345')
    assert tasks.create_task(email, 'Мониторинг цены', idempotency_key='request-67890')['id'] != first['id']
    tasks.control(email, first['id'], 'cancel')


def test_checkpoint_resumes_nonvolatile_results_and_new_run_is_fresh(run):
    _, uid, tid = run
    checkpoints.save([{'round':1,'role':'Расчёт','model':'test','status':'ok','result':'Сумма 42'}, {'status':'ok','result':'Цена 100','search':[{'url':'https://ozon.ru'}]}], uid)
    group, journal = checkpoints.begin(tid, 2, True)
    assert group == 1 and len(journal) == 1 and journal[0]['result'] == 'Сумма 42'
    assert checkpoints.begin(tid, 3, False) == (3, [])


def test_uncertain_and_completed_external_action_not_replayed(run, monkeypatch):
    _, uid, _ = run
    import computer_tools
    calls = []
    async def tool(name, args, user_id): calls.append(name); return 'message_id: 123'
    monkeypatch.setattr(computer_tools, '_run_computer_tool', tool)
    args = {'to':'user@example.com','body':'Отчёт'}
    first = asyncio.run(computer_tools.run_computer_tool('gmail_send', args, uid))
    repeated = asyncio.run(computer_tools.run_computer_tool('gmail_send', args, uid))
    assert first in repeated and 'повтор не отправлялся' in repeated
    assert calls == ['gmail_send']
    key, _ = checkpoints.reserve('gmail_send', {'body':'Сбой'})
    assert 'Повтор заблокирован' in checkpoints.reserve('gmail_send', {'body':'Сбой'})[1]
    assert key


def test_stopped_worker_is_fenced_and_reads_are_not_cached(run):
    email, _, tid = run
    assert not checkpoints.external_action('browse_page', {})
    assert not checkpoints.external_action('http_request', {'method':'GET'})
    assert checkpoints.external_action('http_request', {'method':'POST'})
    tasks.control(email, tid, 'pause')
    with pytest.raises(ValueError): checkpoints.reserve('gmail_send', {'body':'Must not send'})
