import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from app.config import get_settings  # noqa: F401
from app.billing import quota
from app.billing.plans import plan_for
from app.billing.call_budget import reserve, settle
from app.db.engine import SyncSessionLocal
from app.db.models import Subscription
from conversations import conversation_manager as manager


@pytest.fixture
def uid():
    user = 700_000_000 + uuid4().int % 100_000_000
    manager.set_subscription_tier(user, 'pro', 30, from_today=True)
    quota.clear_quota_charge()
    yield user
    quota.refund_quota_charge(); quota.clear_quota_charge()


@pytest.mark.parametrize('tier,total,week,session', [('pro',75_000_000,30_000_000,8_630_000),('proplus',165_000_000,65_500_000,18_660_000),('ultra',510_000_000,202_500_000,57_780_000),('trial',165_000_000,65_500_000,18_660_000)])
def test_shared_plan_limits(tier,total,week,session):
    plan = plan_for(tier)
    assert (plan['total_tokens'],plan['weekly_tokens'],plan['session_tokens']) == (total,week,session)


def test_existing_counters_are_added_without_reset_or_double_debit(uid):
    manager.debit_plan_tokens(uid,'chat',1_000_000)
    manager.debit_plan_tokens(uid,'computer',500_000)
    before = manager.get_subscription(uid)
    view = quota.usage_view(before.copy())
    after = manager.get_subscription(uid)
    assert view['shared']['used'] == 1_500_000 and view['shared']['remaining'] == 73_500_000
    assert view['breakdown'] == {'chat':1_000_000,'computer':500_000}
    assert view['chat'] == view['computer'] == view['shared']
    for name in ('chat_tokens_used','computer_tokens_used','session_chat_used','session_computer_used','week_chat_used','week_computer_used'):
        assert before[name] == after[name]


def test_parallel_chat_and_orchestrator_share_one_reservation_limit(uid):
    plan = plan_for('pro'); used = plan['session_tokens'] - 10_000
    manager.debit_plan_tokens(uid,'chat',used)
    def claim(pool):
        try: return reserve(uid,pool,'gpt-6-sol',100,1000)
        except quota.QuotaError: return None
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim,['chat','computer']))
    assert sum(result is not None for result in results) == 1
    assert quota.usage_view(manager.get_subscription(uid))['windows']['shared']['session']['remaining'] == 0
    for result,pool in zip(results,['chat','computer']):
        if result: settle(uid,result[0],0,pool)
    assert quota.usage_view(manager.get_subscription(uid))['shared']['used'] == used


def test_search_is_one_of_thirty_replies_and_many_queries_count_once(uid):
    manager.set_subscription_tier(uid,'free',0,from_today=True)
    assert manager.consume_daily_counter(uid,'daily_gpt54',30)
    quota.note_quota_charge(uid,'daily_gpt54')
    token = quota.billing_user.set(uid)
    async def run():
        await asyncio.gather(*(quota.assert_search_allowed() for _ in range(5)))
        await quota.assert_search_allowed()
    try: asyncio.run(run())
    finally: quota.billing_user.reset(token)
    view = quota.usage_view(manager.get_subscription(uid))
    assert view['free_daily']['replies'] == view['free_daily']['searches'] == 1
    assert view['free_daily']['searches_limit'] == 15
    quota.refund_quota_charge(); quota.refund_quota_charge()
    view = quota.usage_view(manager.get_subscription(uid))
    assert view['free_daily']['replies'] == view['free_daily']['searches'] == 0


def test_free_search_subset_and_total_are_both_enforced(uid):
    manager.set_subscription_tier(uid,'free',0,from_today=True)
    for _ in range(15): manager.mark_free_reply_search(uid,False)
    assert manager.consume_daily_counter(uid,'daily_gpt54',30)
    with pytest.raises(quota.QuotaError): manager.mark_free_reply_search(uid,True)
    assert quota.usage_view(manager.get_subscription(uid))['free_daily']['replies'] == 16
    for _ in range(14): assert manager.consume_daily_counter(uid,'daily_gpt54',30)
    assert not manager.consume_daily_counter(uid,'daily_gpt54',30)
    view=quota.usage_view(manager.get_subscription(uid))
    assert view['free_daily']['replies']==30 and view['free_daily']['searches']==15


def test_server_search_counts_once_even_for_multiple_queries_and_cache(uid,monkeypatch):
    from app.services import server_search
    manager.set_subscription_tier(uid,'free',0,from_today=True)
    assert manager.consume_daily_counter(uid,'daily_gpt54',30)
    quota.note_quota_charge(uid,'daily_gpt54')
    async def fetch(provider,query):
        return [{'title':'Python asyncio docs','url':'https://docs.python.org/3/library/asyncio.html','snippet':'Python asyncio documentation'}], 'ok'
    monkeypatch.setattr(server_search,'_fetch',fetch)
    token=quota.billing_user.set(uid)
    async def run():
        await server_search.server_search('Python asyncio docs')
        await server_search.server_search('Python asyncio docs')
        await server_search.server_search('Python asyncio documentation')
    try: asyncio.run(run())
    finally: quota.billing_user.reset(token)
    assert quota.usage_view(manager.get_subscription(uid))['free_daily']['searches']==1
    assert quota.usage_view(manager.get_subscription(uid))['free_daily']['replies']==1
