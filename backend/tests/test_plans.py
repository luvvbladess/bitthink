from app.billing.plans import (
    ULTRA_MODELS,
    allowed_models,
    canonical_tier,
    clamp_model,
    computer_models,
    our_tokens,
    plan_for,
    research_model,
)
from app.billing.quota import usage_view
from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path
from db_conversations import DatabaseConversationManager


def test_canonical_aliases():
    assert canonical_tier("start") == "pro"
    assert canonical_tier("max") == "ultra"
    assert canonical_tier("proplus") == "proplus"
    assert canonical_tier("unknown") == "free"


def test_pro_price_and_pools():
    plan = plan_for("pro")
    assert plan["price_rub"] == 1_990
    assert plan["chat_tokens"] == 30_000_000
    assert plan["computer_tokens"] == 7_200_000
    assert plan["chat_week"] == 7_500_000
    assert plan["chat_session"] == 2_160_000
    assert plan["computer_week"] == 1_800_000
    assert plan["computer_session"] == 516_000


def test_multipliers_and_long_context():
    assert our_tokens("gpt-5.6-luna", 100, 50) == 150
    assert our_tokens("kimi-k2.6", 100, 0) == 400
    assert our_tokens("gpt-5.6-terra", 10, 0) == 130
    assert our_tokens("gpt-5.6-sol", 10, 0) == 320
    assert our_tokens("gpt-6-astra", 10, 0) == 900
    assert our_tokens("gpt-5.6-luna", 272_001, 0) == 272_001 * 2
    assert our_tokens("gpt-5.6-luna", 100, 0, 100) == 25
    assert our_tokens("gpt-5.6-luna", 100, 50, 0) == 150
    assert our_tokens("gpt-5.6-luna", 100, 0, 0, 100) == 125


def test_clamp_and_research_access():
    assert clamp_model("pro", "gpt-5.6-terra") == "gpt-5.6-luna"
    assert clamp_model("pro", "gpt-5.6-sol") == "gpt-5.6-luna"
    assert clamp_model("proplus", "gpt-5.6-sol") == "gpt-5.6-terra"
    assert clamp_model("ultra", "gpt-5.6-sol") == "gpt-5.6-sol"
    assert clamp_model("ultra", "gpt-6-astra") == "gpt-6-astra"
    assert clamp_model("proplus", "gpt-6-astra") == "gpt-5.6-terra"
    assert clamp_model("pro", "gpt-6-astra") == "gpt-5.6-luna"
    assert research_model("pro") is None
    assert research_model("proplus") == "gpt-5.6-terra"
    assert research_model("ultra") == "gpt-5.6-sol"
    assert "gpt-6-astra" in computer_models("ultra")
    assert "gpt-6-astra" not in computer_models("proplus")


def test_creator_has_every_ultra_capability():
    ultra = allowed_models("ultra")
    creator = allowed_models("creator")
    assert set(ULTRA_MODELS) <= creator
    assert ultra <= creator
    assert "gpt-6-astra" in creator
    assert clamp_model("creator", "gpt-6-astra") == "gpt-6-astra"
    assert research_model("creator") == research_model("ultra")
    assert set(computer_models("ultra")) <= set(computer_models("creator"))
    assert "gpt-6-astra" in computer_models("creator")
    assert plan_for("creator").get("unlimited") is True


def test_usage_view_and_debit():
    mgr = DatabaseConversationManager()
    uid = 91001
    mgr.set_subscription_tier(uid, "pro", 30)
    mgr.debit_plan_tokens(uid, "chat", 1_000_000, model="gpt-5.6-luna")
    mgr.debit_plan_tokens(uid, "computer", 500_000, model="gpt-5.6-luna")
    mgr.debit_plan_images(uid, 2)
    view = usage_view(mgr.get_subscription(uid))
    assert view["tier"] == "pro"
    assert view["chat"]["used"] == 1_000_000
    assert view["chat"]["remaining"] == 29_000_000
    assert view["computer"]["used"] == 500_000
    assert view["computer"]["remaining"] == 6_700_000
    assert view["images"]["used"] == 2
    assert view["images"]["remaining"] == 23
    assert view["windows"]["chat"]["session"]["used"] == 1_000_000
    assert view["windows"]["chat"]["session"]["remaining"] == 1_160_000
    assert view["windows"]["chat"]["week"]["used"] == 1_000_000
    assert view["windows"]["chat"]["week"]["remaining"] == 6_500_000
    assert view["windows"]["computer"]["session"]["used"] == 500_000


def test_legacy_start_becomes_pro():
    mgr = DatabaseConversationManager()
    uid = 91002
    mgr.set_subscription_tier(uid, "start", 30)
    assert mgr.get_subscription(uid)["tier"] == "pro"


def test_session_and_week_block_before_month():
    from app.billing.quota import QuotaError, assert_can_use
    from app.db.engine import SyncSessionLocal
    from app.db.models import Subscription

    mgr = DatabaseConversationManager()
    uid = 91003
    mgr.set_subscription_tier(uid, "pro", 30)
    mgr.debit_plan_tokens(uid, "chat", 2_160_000)
    view = usage_view(mgr.get_subscription(uid))
    assert view["windows"]["chat"]["session"]["remaining"] == 0
    assert view["chat"]["remaining"] == 27_840_000
    try:
        assert_can_use(uid, "chat", "gpt-5.6-luna")
        raise AssertionError("session should block")
    except QuotaError as err:
        assert "Пятичасовое" in str(err)

    uid = 91004
    mgr.set_subscription_tier(uid, "pro", 30)
    mgr.get_subscription(uid)
    with SyncSessionLocal() as session:
        sub = session.query(Subscription).filter_by(user_id=uid).first()
        sub.week_chat_used = 7_500_000
        session.commit()
    view = usage_view(mgr.get_subscription(uid))
    assert view["windows"]["chat"]["week"]["remaining"] == 0
    try:
        assert_can_use(uid, "chat", "gpt-5.6-luna")
        raise AssertionError("week should block")
    except QuotaError as err:
        assert "Недельный" in str(err)


def test_expired_session_resets():
    import time

    from app.billing.plans import SESSION_SECONDS
    from app.db.engine import SyncSessionLocal
    from app.db.models import Subscription

    mgr = DatabaseConversationManager()
    uid = 91005
    mgr.set_subscription_tier(uid, "pro", 30)
    mgr.debit_plan_tokens(uid, "chat", 1_000_000)
    with SyncSessionLocal() as session:
        sub = session.query(Subscription).filter_by(user_id=uid).first()
        sub.session_started_at = int(time.time()) - SESSION_SECONDS - 10
        session.commit()
    view = usage_view(mgr.get_subscription(uid))
    assert view["windows"]["chat"]["session"]["used"] == 0
    assert view["windows"]["chat"]["session"]["remaining"] == 2_160_000
    assert view["chat"]["used"] == 1_000_000


def test_from_today_replaces_expiry_instead_of_stacking():
    import time

    mgr = DatabaseConversationManager()
    uid = 93101
    mgr.set_subscription_tier(uid, "pro", 30)
    first = mgr.get_subscription(uid)["expires_at"]
    mgr.set_subscription_tier(uid, "pro", 30)
    stacked = mgr.get_subscription(uid)["expires_at"]
    assert stacked >= first + 29 * 86400
    mgr.debit_plan_tokens(uid, "chat", 50_000)
    mgr.set_subscription_tier(uid, "ultra", 10, from_today=True)
    reset = mgr.get_subscription(uid)
    now = int(time.time())
    assert reset["tier"] == "ultra"
    assert abs(reset["expires_at"] - (now + 10 * 86400)) < 8
    assert reset["chat_tokens_used"] == 0


def test_reset_non_admins_skips_admins():
    import uuid

    from app.db.engine import SyncSessionLocal
    from app.db.models import User

    mgr = DatabaseConversationManager()
    token = uuid.uuid4().hex[:12]
    user_id = 10_000_000 + (uuid.uuid4().int % 1_000_000)
    admin_id = 20_000_000 + (uuid.uuid4().int % 1_000_000)
    mgr.set_subscription_tier(user_id, "pro", 30)
    mgr.set_subscription_tier(admin_id, "ultra", 30)
    admin_expiry = mgr.get_subscription(admin_id)["expires_at"]
    with SyncSessionLocal() as session:
        session.add(
            User(
                email=f"reset-user-{token}@example.test",
                password_hash="x",
                role="user",
                bot_user_id=user_id,
                first_name="User",
            )
        )
        session.add(
            User(
                email=f"reset-admin-{token}@example.test",
                password_hash="x",
                role="admin",
                bot_user_id=admin_id,
                first_name="Admin",
            )
        )
        session.commit()

    result = mgr.reset_non_admin_subscriptions("free", bot_user_ids=[user_id, admin_id])
    assert result["tier"] == "free"
    assert result["reset"] == 1
    user = mgr.get_subscription(user_id)
    assert user["tier"] == "free"
    assert user["expires_at"] == 0
    admin = mgr.get_subscription(admin_id)
    assert admin["expires_at"] == admin_expiry
    assert admin["tier"] in ("ultra", "creator")


def test_spend_summary_uses_vendor_rates():
    from app.billing.costs import model_cost_usd, spend_summary

    assert abs(model_cost_usd("gpt-5.6-luna", 1_000_000, 0) - 0.25) < 1e-9
    assert abs(model_cost_usd("gpt-5.6-sol", 0, 1_000_000) - 14.0) < 1e-9
    assert abs(model_cost_usd("gpt-6-astra", 1_000_000, 0) - 10.0) < 1e-9
    assert abs(model_cost_usd("gpt-image-2.5-sunburst", 0, 0, 1) - 0.08) < 1e-9
    assert abs(model_cost_usd("gpt-image-2", 0, 0, 1) - 0.08) < 1e-9
    assert abs(model_cost_usd("gpt-image-1.5", 0, 0, 2) - 0.16) < 1e-9
    summary = spend_summary(
        {
            "gpt-5.6-luna": {"input": 1_000_000, "output": 0, "images": 0},
            "gpt-image-1.5": {"input": 0, "output": 0, "images": 1},
        }
    )
    assert abs(summary["usd"] - 0.33) < 1e-9
    assert summary["models"][0]["model"] == "gpt-5.6-luna"
