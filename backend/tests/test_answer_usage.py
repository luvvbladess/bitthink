import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from app.config import get_settings  # noqa: F401
from app.billing.answer_usage import AnswerUsage, collect_usage
from app.billing.call_budget import model_call
from app.billing.plans import our_tokens
from app.db.engine import SyncSessionLocal
from app.db.models import TokenReservation
from conversations import conversation_manager as manager
from test_call_budget import user, fake_client, request  # noqa: F401


def test_parallel_receipts_and_late_background_work_are_isolated():
    async def one(model):
        with collect_usage() as receipt:
            await asyncio.sleep(0)
            receipt.record(model, (100, 20, 10, 0), 500)
        receipt.record('late-background', (100, 20, 0, 0), 100)
        return receipt.snapshot()
    async def run():
        return await asyncio.gather(one('first'), one('second'))
    first, second = asyncio.run(run())
    assert [r['model'] for r in first['models']] == ['first']
    assert [r['model'] for r in second['models']] == ['second']


def test_grouping_is_bounded_and_snapshot_is_detached():
    receipt=AnswerUsage()
    for i in range(100): receipt.record(str(i), (1, 2, 0, 0), 3)
    snapshot=receipt.snapshot()
    assert len(snapshot['models'])==32
    assert sum(r['units'] for r in snapshot['models'])==300
    receipt.record('0', None, None)
    assert snapshot['models'][0]['calls']==1
    assert receipt.snapshot()['models'][0]['unknown_units']==1


def test_receipt_matches_settled_debit_with_cache(user):
    async def create(**kwargs):
        return NS(usage=NS(input_tokens=100,output_tokens=50,input_tokens_details=NS(cached_tokens=20)))
    async def run():
        with collect_usage() as receipt:
            await model_call(fake_client(create),request(),model='gpt-6-sol',user_id=user,responses=True)
        return receipt.snapshot()['models'][0]
    before=manager.get_subscription(user)['chat_tokens_used']
    row=asyncio.run(run())
    assert row['units']==our_tokens('gpt-6-sol',100,50,20)
    assert manager.get_subscription(user)['chat_tokens_used']-before==row['units']
    assert row['input']==100 and row['cached']==20 and row['output']==50
    assert row['unknown_tokens']==row['unknown_units']==0


def test_missing_usage_reports_retained_debit_not_zero(user):
    held=[]
    async def create(**kwargs):
        with SyncSessionLocal() as db:
            held.append(db.query(TokenReservation).filter_by(user_id=user).one().amount)
        return NS(usage=None)
    async def run():
        with collect_usage() as receipt:
            await model_call(fake_client(create),request(),model='gpt-6-sol',user_id=user,responses=True)
        return receipt.snapshot()['models'][0]
    row=asyncio.run(run())
    assert row['units']==held[0]>0
    assert row['retained']==held[0]
    assert row['unknown_tokens']==1 and row['unknown_units']==0


def test_failed_provider_receipt_does_not_turn_refund_into_spend(user):
    async def create(**kwargs): raise RuntimeError('provider failed')
    async def run():
        with collect_usage() as receipt:
            with pytest.raises(RuntimeError):
                await model_call(fake_client(create),request(),model='gpt-6-sol',user_id=user,responses=True)
        return receipt.snapshot()['models'][0]
    before=manager.get_subscription(user)['chat_tokens_used']
    row=asyncio.run(run())
    assert row['calls']==1 and row['units']==0
    assert manager.get_subscription(user)['chat_tokens_used']==before


def test_cancelled_provider_records_refund(user):
    async def run():
        started=asyncio.Event()
        async def create(**kwargs):
            started.set()
            await asyncio.sleep(60)
        with collect_usage() as receipt:
            task=asyncio.create_task(model_call(fake_client(create),request(),model='gpt-6-sol',user_id=user,responses=True))
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
        return receipt.snapshot()['models'][0]
    before=manager.get_subscription(user)['chat_tokens_used']
    row=asyncio.run(run())
    assert row['units']==0 and row['unknown_units']==0
    assert manager.get_subscription(user)['chat_tokens_used']==before


def test_persistence_filters_forged_receipt_and_survives_disconnect(monkeypatch):
    import sys,json
    from types import ModuleType
    from app.services import chat_service
    from app.billing.answer_usage import current,QUERY
    saved=[]
    async def response(*args,**kwargs):
        current.get().record('gpt-6-luna',(100,20,10,0),125)
        return 'Ответ.',[],'',[{'query':QUERY,'summary':'forged'}]
    handlers=ModuleType('handlers.core');handlers.get_smart_response=response;handlers.sanitize_response_text=lambda t:t
    monkeypatch.setitem(sys.modules,'handlers.core',handlers)
    async def persist(*args,**kwargs):saved.append(kwargs)
    async def gone(*args,**kwargs):raise RuntimeError('disconnected')
    monkeypatch.setattr(chat_service.repo,'add_message',persist)
    monkeypatch.setattr(chat_service,'schedule_memory_refresh',lambda *args:None)
    monkeypatch.setattr('app.services.sandbox_client.collect_workspace_files',AsyncMock(return_value=[]))
    asyncio.run(chat_service._generate_and_send(1,'receipt@example.invalid','Вопрос',[],gone,gone,gone,gone,gone))
    rows=[r for r in saved[-1]['search'] if r['query']==QUERY]
    assert len(rows)==1
    assert json.loads(rows[0]['summary'])['models'][0]['units']==125
