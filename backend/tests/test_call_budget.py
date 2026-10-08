import asyncio
import threading
import time
import uuid
from types import SimpleNamespace

import pytest

from app.billing.call_budget import model_call, reserve, settle, token_counts
from app.billing.plans import our_tokens, plan_for
from app.billing.quota import QuotaError, assert_can_use, billing_pool, billing_scope, billing_user, release_paid_hold
from app.config import get_settings  # noqa: F401
from app.db.engine import SyncSessionLocal
from app.db.models import Subscription, TokenReservation
from conversations import conversation_manager as manager


@pytest.fixture
def user():
    uid = 500_000_000 + uuid.uuid4().int % 100_000_000
    manager.set_subscription_tier(uid, "pro", 30, from_today=True)
    pool_token = billing_pool.set("chat")
    user_token = billing_user.set(None)
    yield uid
    release_paid_hold()
    billing_pool.reset(pool_token)
    billing_user.reset(user_token)


def leave_session(uid, remaining=10_000, pool="chat"):
    limit = plan_for("pro")[f"{pool}_session"]
    manager.debit_plan_tokens(uid, pool, limit - remaining)
    return limit


def fake_client(create, inp=100):
    async def count(**kwargs):
        return SimpleNamespace(input_tokens=inp)
    return SimpleNamespace(responses=SimpleNamespace(create=create, input_tokens=SimpleNamespace(count=count)))


def request():
    return {"model": "gpt-6.1-sol", "input": "hello", "max_output_tokens": 1000}


def test_response_cap_refund_and_single_actual_debit(user):
    limit = leave_session(user)
    calls = []
    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(usage=SimpleNamespace(input_tokens=100, output_tokens=50,
            input_tokens_details=SimpleNamespace(cached_tokens=20)))
    asyncio.run(model_call(fake_client(create), request(), model="gpt-6-sol", user_id=user, responses=True))
    assert calls[0]["max_output_tokens"] == 375
    actual = our_tokens("gpt-6-sol", 100, 50, 20)
    sub = manager.get_subscription(user)
    assert sub["session_chat_used"] == limit - 10_000 + actual
    assert sub["chat_tokens_used"] == limit - 10_000 + actual
    assert manager.get_month_usage(user)["gpt-6-sol"]["input"] == 100
    with SyncSessionLocal() as session:
        assert session.query(TokenReservation).filter_by(user_id=user).count() == 0


def test_parallel_calls_cannot_reserve_the_same_remainder(user):
    leave_session(user)
    results = []
    def attempt():
        try:
            results.append(reserve(user, "chat", "gpt-6-sol", 100, 1000))
        except QuotaError:
            results.append(None)
    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sum(result is not None for result in results) == 1
    hold, cap = next(result for result in results if result is not None)
    assert cap == 375
    settle(user, hold, 0)


def test_each_tool_hop_rechecks_remaining_budget(user):
    leave_session(user)
    calls = []
    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(usage=SimpleNamespace(input_tokens=100, output_tokens=350))
    async def run():
        client = fake_client(create)
        await model_call(client, request(), model="gpt-6-sol", user_id=user, responses=True)
        with pytest.raises(QuotaError):
            await model_call(client, request(), model="gpt-6-sol", user_id=user, responses=True)
    asyncio.run(run())
    assert len(calls) == 1


def test_provider_error_and_cancellation_refund_only_their_reservation(user):
    leave_session(user)
    before = manager.get_subscription(user)["chat_tokens_used"]
    async def fail(**kwargs):
        raise RuntimeError("provider unavailable")
    with pytest.raises(RuntimeError):
        asyncio.run(model_call(fake_client(fail), request(), model="gpt-6-sol", user_id=user, responses=True))
    assert manager.get_subscription(user)["chat_tokens_used"] == before
    async def run_cancel():
        started = asyncio.Event()
        async def create(**kwargs):
            started.set()
            await asyncio.Future()
        task = asyncio.create_task(model_call(fake_client(create), request(), model="gpt-6-sol", user_id=user, responses=True))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run_cancel())
    assert manager.get_subscription(user)["chat_tokens_used"] == before


def test_abandoned_hold_is_recovered_before_precheck(user):
    leave_session(user)
    before = manager.get_subscription(user)["chat_tokens_used"]
    hold, _ = reserve(user, "chat", "gpt-6-sol", 100, 1000)
    with SyncSessionLocal() as session:
        row = session.get(TokenReservation, hold)
        row.expires_at = int(time.time()) - 1
        session.commit()
    assert manager.get_subscription(user)["chat_tokens_used"] == before


def test_old_hold_does_not_refund_new_session_or_reissued_subscription(user):
    leave_session(user)
    hold, _ = reserve(user, "chat", "gpt-6-sol", 100, 1000)
    with SyncSessionLocal() as session:
        sub = session.query(Subscription).filter_by(user_id=user).one()
        sub.session_started_at += 1
        sub.session_chat_used = 300
        session.commit()
    settle(user, hold, 0)
    assert manager.get_subscription(user)["session_chat_used"] == 300
    hold, _ = reserve(user, "chat", "gpt-6-sol", 100, 1000)
    manager.set_subscription_tier(user, "pro", 10, from_today=True)
    manager.debit_plan_tokens(user, "chat", 999)
    settle(user, hold, 0)
    assert manager.get_subscription(user)["chat_tokens_used"] == 999


def test_computer_budget_is_independent_and_missing_usage_does_not_reopen_wallet(user):
    limit = leave_session(user, pool="computer")
    token = billing_pool.set("computer")
    async def create(**kwargs):
        return SimpleNamespace(usage=None)
    try:
        asyncio.run(model_call(fake_client(create), request(), model="gpt-6-sol", user_id=user, responses=True))
    finally:
        billing_pool.reset(token)
    sub = manager.get_subscription(user)
    assert sub["session_computer_used"] == limit
    assert sub["chat_tokens_used"] == 0


def test_child_tasks_refund_shared_initial_hold_only_once(user):
    manager.debit_plan_tokens(user, "chat", 500)
    assert_can_use(user)
    async def run():
        async def release():
            release_paid_hold()
        await asyncio.gather(release(), release())
    asyncio.run(run())
    assert manager.get_subscription(user)["chat_tokens_used"] == 500


def test_nested_attribution_is_restored_after_turn(user):
    @billing_scope
    async def nested(user_id=None):
        return billing_user.get()
    @billing_scope
    async def turn(user_id):
        assert await nested() == user_id
        assert await nested(123) == 123
        assert billing_user.get() == user_id
    asyncio.run(turn(user))
    assert billing_user.get() is None


def test_cache_write_usage_is_settled_at_the_vendor_rate(user):
    limit = leave_session(user)
    async def create(**kwargs):
        return SimpleNamespace(usage=SimpleNamespace(input_tokens=100, output_tokens=50,
            input_tokens_details=SimpleNamespace(cached_tokens=0, cache_creation_input_tokens=20)))
    asyncio.run(model_call(fake_client(create), request(), model="gpt-6-sol", user_id=user, responses=True))
    actual = our_tokens("gpt-6-sol", 100, 50, 0, 20)
    assert manager.get_subscription(user)["session_chat_used"] == limit - 10_000 + actual
    assert token_counts({"prompt_tokens": 100, "completion_tokens": 50, "prompt_cache_hit_tokens": 20}) == (100, 50, 20, 0)


def test_reservation_migration_creates_and_reuses_runtime_table():
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path
    from sqlalchemy import create_engine, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).resolve().parents[1] / "alembic/versions/017_token_reservations.py"
    spec = spec_from_file_location("reservation_migration", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection, Operations.context(MigrationContext.configure(engine.connect())):
        module.upgrade()
        assert inspect(engine).has_table("token_reservations")
        assert "subscription_expires_at" in {col["name"] for col in inspect(engine).get_columns("token_reservations")}
        module.upgrade()  # Startup may already have created the table.
        module.downgrade()
        assert not inspect(engine).has_table("token_reservations")
