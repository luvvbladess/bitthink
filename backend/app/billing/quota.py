"""Token wallets: 5-hour session, week (Monday MSK), month, plus Nano cushion."""

from __future__ import annotations

import time
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from app.billing.plans import (
    NANO_CUSHION_PER_DAY,
    SESSION_SECONDS,
    canonical_tier,
    our_tokens,
    plan_for,
)

billing_pool: ContextVar[str] = ContextVar("billing_pool", default="chat")

PoolName = Literal["chat", "computer"]
MSK = timezone(timedelta(hours=3))

_WEEKDAY_WHEN = (
    "в понедельник",
    "во вторник",
    "в среду",
    "в четверг",
    "в пятницу",
    "в субботу",
    "в воскресенье",
)


class QuotaError(Exception):
    def __init__(self, message: str, code: str = "quota"):
        super().__init__(message)
        self.code = code


def _manager():
    import conversations

    return conversations.conversation_manager


def msk_now(now_ts: int | None = None) -> datetime:
    if now_ts is None:
        return datetime.now(MSK)
    return datetime.fromtimestamp(int(now_ts), MSK)


def msk_monday(now: datetime | None = None) -> str:
    now = now or msk_now()
    return (now.date() - timedelta(days=now.weekday())).isoformat()


def next_midnight_ts(now: datetime | None = None) -> int:
    now = now or msk_now()
    nxt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    return int(nxt.timestamp())


def next_monday_ts(now: datetime | None = None) -> int:
    now = now or msk_now()
    days = 7 - now.weekday()
    nxt = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days)
    return int(nxt.timestamp())


def next_month_ts(now: datetime | None = None) -> int:
    now = now or msk_now()
    if now.month == 12:
        nxt = datetime(now.year + 1, 1, 1, tzinfo=MSK)
    else:
        nxt = datetime(now.year, now.month + 1, 1, tzinfo=MSK)
    return int(nxt.timestamp())


def human_reset(ts: int) -> str:
    if not ts:
        return ""
    now = msk_now()
    then = datetime.fromtimestamp(int(ts), MSK)
    clock = then.strftime("%H:%M")
    if then.date() == now.date():
        return f"в {clock}"
    if then.date() == now.date() + timedelta(days=1):
        return f"завтра в {clock}"
    return f"{_WEEKDAY_WHEN[then.weekday()]} в {clock}"


def refresh_windows(sub: dict[str, Any], now_ts: int | None = None) -> dict[str, Any]:
    """Expire the 5-hour window and roll daily / week / month counters. Mutates sub."""
    now = msk_now(now_ts)
    now_ts = int(now.timestamp())
    today = now.strftime("%Y-%m-%d")
    period = now.strftime("%Y-%m")
    monday = msk_monday(now)

    if sub.get("last_reset_date") != today:
        sub["daily_nano_mini"] = 0
        sub["daily_gpt54"] = 0
        sub["daily_director"] = 0
        sub["daily_images"] = 0
        sub["daily_docs"] = 0
        sub["last_reset_date"] = today
    if (sub.get("nano_cushion_date") or "") != today:
        sub["nano_cushion_date"] = today
        sub["nano_cushion_used"] = 0
    if (sub.get("period_start") or "") != period:
        sub["period_start"] = period
        sub["chat_tokens_used"] = 0
        sub["computer_tokens_used"] = 0
        sub["images_used"] = 0
    if (sub.get("week_start") or "") != monday:
        sub["week_start"] = monday
        sub["week_chat_used"] = 0
        sub["week_computer_used"] = 0
    started = int(sub.get("session_started_at") or 0)
    if started and now_ts >= started + SESSION_SECONDS:
        sub["session_started_at"] = 0
        sub["session_chat_used"] = 0
        sub["session_computer_used"] = 0
    return sub


def apply_token_debit(sub: dict[str, Any], pool: str, amount: int) -> dict[str, Any]:
    refresh_windows(sub)
    plan = plan_for(sub.get("tier"))
    if plan.get("unlimited") or canonical_tier(sub.get("tier")) == "free" or amount <= 0:
        return sub
    now_ts = int(time.time())
    started = int(sub.get("session_started_at") or 0)
    if not started or now_ts >= started + SESSION_SECONDS:
        sub["session_started_at"] = now_ts
        sub["session_chat_used"] = 0
        sub["session_computer_used"] = 0
    if pool == "computer":
        sub["computer_tokens_used"] = int(sub.get("computer_tokens_used") or 0) + amount
        sub["session_computer_used"] = int(sub.get("session_computer_used") or 0) + amount
        sub["week_computer_used"] = int(sub.get("week_computer_used") or 0) + amount
        return sub
    limit = int(plan.get("chat_tokens") or 0)
    used = int(sub.get("chat_tokens_used") or 0)
    if limit and used >= limit:
        return sub
    sub["chat_tokens_used"] = used + amount
    sub["session_chat_used"] = int(sub.get("session_chat_used") or 0) + amount
    sub["week_chat_used"] = int(sub.get("week_chat_used") or 0) + amount
    return sub


def _window(
    used: int,
    limit: int,
    resets_at: int,
    *,
    unlimited: bool,
    active: bool = True,
) -> dict[str, Any]:
    used = int(used or 0)
    limit = 0 if unlimited else int(limit or 0)
    remaining = None if unlimited else max(0, limit - used)
    ratio = 0.0 if unlimited or not limit else min(1.0, used / limit)
    return {
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "resets_at": int(resets_at or 0),
        "ratio": round(ratio, 4),
        "active": bool(active) and not unlimited,
    }


def usage_view(sub: dict[str, Any]) -> dict[str, Any]:
    refresh_windows(sub)
    tier = canonical_tier(sub.get("tier"))
    plan = plan_for(tier)
    unlimited = bool(plan.get("unlimited"))
    chat_limit = 0 if unlimited else int(plan.get("chat_tokens") or 0)
    computer_limit = 0 if unlimited else int(plan.get("computer_tokens") or 0)
    image_limit = 0 if unlimited else int(plan.get("images") or 0)
    chat_used = int(sub.get("chat_tokens_used") or 0)
    computer_used = int(sub.get("computer_tokens_used") or 0)
    images_used = int(sub.get("images_used") or 0)
    now = msk_now()
    now_ts = int(now.timestamp())
    started = int(sub.get("session_started_at") or 0)
    session_active = bool(started) and now_ts < started + SESSION_SECONDS
    session_reset = started + SESSION_SECONDS if session_active else 0
    week_reset = next_monday_ts(now)
    month_reset = next_month_ts(now)
    paid = not unlimited and tier != "free"
    chat_session = _window(
        int(sub.get("session_chat_used") or 0) if session_active else 0,
        int(plan.get("chat_session") or 0) if paid else 0,
        session_reset,
        unlimited=unlimited,
        active=session_active if paid else False,
    )
    chat_week = _window(
        int(sub.get("week_chat_used") or 0),
        int(plan.get("chat_week") or 0) if paid else 0,
        week_reset,
        unlimited=unlimited,
        active=paid,
    )
    chat_month = _window(chat_used, chat_limit, month_reset, unlimited=unlimited, active=paid)
    computer_session = _window(
        int(sub.get("session_computer_used") or 0) if session_active else 0,
        int(plan.get("computer_session") or 0) if paid else 0,
        session_reset,
        unlimited=unlimited,
        active=session_active if paid else False,
    )
    computer_week = _window(
        int(sub.get("week_computer_used") or 0),
        int(plan.get("computer_week") or 0) if paid else 0,
        week_reset,
        unlimited=unlimited,
        active=paid,
    )
    computer_month = _window(
        computer_used, computer_limit, month_reset, unlimited=unlimited, active=paid
    )
    free_replies = int(sub.get("daily_gpt54") or 0)
    free_replies_limit = int(plan.get("daily_replies") or 0)
    free_searches = int(sub.get("daily_nano_mini") or 0)
    free_searches_limit = int(plan.get("daily_searches") or 0)
    midnight = next_midnight_ts(now)
    return {
        "tier": tier,
        "tier_raw": sub.get("tier") or "free",
        "name": plan["name"],
        "expires_at": sub.get("expires_at") or 0,
        "period": sub.get("period_start") or "",
        "unlimited": unlimited,
        "chat": {
            "used": chat_used,
            "limit": chat_limit,
            "remaining": None if unlimited else max(0, chat_limit - chat_used),
        },
        "computer": {
            "used": computer_used,
            "limit": computer_limit,
            "remaining": None if unlimited else max(0, computer_limit - computer_used),
        },
        "images": {
            "used": images_used,
            "limit": image_limit,
            "remaining": None if unlimited else max(0, image_limit - images_used),
        },
        "windows": {
            "chat": {"session": chat_session, "week": chat_week, "month": chat_month},
            "computer": {
                "session": computer_session,
                "week": computer_week,
                "month": computer_month,
            },
        },
        "nano_cushion": {
            "used": int(sub.get("nano_cushion_used") or 0),
            "limit": 0 if unlimited or tier == "free" else NANO_CUSHION_PER_DAY,
            "date": sub.get("nano_cushion_date") or "",
        },
        "free_daily": {
            "replies": free_replies,
            "replies_limit": free_replies_limit,
            "searches": free_searches,
            "searches_limit": free_searches_limit,
            "resets_at": midnight if tier == "free" else 0,
        },
        "multipliers": {
            "Luna / Nano": 1,
            "Kimi": 4,
            "DeepSeek": 5,
            "Terra": 13,
            "Sol": 32,
            "Astra": 90,
        },
    }


def _block_window(window: dict[str, Any], empty_message: str) -> None:
    remaining = window.get("remaining")
    if remaining is None or remaining > 0:
        return
    when = human_reset(int(window.get("resets_at") or 0))
    if when:
        raise QuotaError(f"{empty_message} Снова можно будет {when} по Москве.", "quota")
    raise QuotaError(empty_message, "quota")


def assert_can_use(user_id: int, pool: PoolName = "chat", model: str = "gpt-5.6-luna") -> None:
    sub = _manager().get_subscription(user_id)
    view = usage_view(sub)
    if view["unlimited"]:
        return
    if view["tier"] == "free":
        if pool == "computer":
            raise QuotaError("Пилот недоступен на базовом тарифе. Нужен Pro.", "plan")
        if model == "kimi-k2.6":
            used = view["free_daily"]["searches"]
            cap = view["free_daily"]["searches_limit"]
            if cap and used >= cap:
                raise QuotaError("На сегодня поиски закончились. Завтра снова 5, либо оформите Pro.", "quota")
            return
        used = view["free_daily"]["replies"]
        cap = view["free_daily"]["replies_limit"]
        if cap and used >= cap:
            raise QuotaError("На сегодня 30 ответов закончились. Завтра снова, либо оформите Pro.", "quota")
        return

    family = view["windows"]["computer" if pool == "computer" else "chat"]
    if pool == "computer":
        _block_window(family["session"], "Пятичасовое окно Пилота закончилось.")
        _block_window(family["week"], "Недельный лимит Пилота закончился.")
        remaining = view["computer"]["remaining"]
        if remaining is not None and remaining <= 0:
            raise QuotaError("Токены Пилота на этот месяц закончились. Чат при этом продолжает работать.", "quota")
        return

    _block_window(family["session"], "Пятичасовое окно чата закончилось.")
    _block_window(family["week"], "Недельный лимит чата закончился.")
    remaining = view["chat"]["remaining"]
    if remaining is not None and remaining <= 0:
        if model == "gpt-5-nano" and view["nano_cushion"]["used"] < view["nano_cushion"]["limit"]:
            return
        raise QuotaError(
            "Токены чата на этот месяц закончились. Ещё доступны быстрые ответы Nano, либо тариф выше.",
            "quota",
        )


def debit_model_usage(
    user_id: int,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_input_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> int:
    charged = our_tokens(model, input_tokens, output_tokens, cached_input_tokens, cache_write_tokens)
    if charged <= 0:
        return 0
    pool = billing_pool.get()
    if pool not in {"chat", "computer"}:
        pool = "chat"
    _manager().debit_plan_tokens(user_id, pool, charged, model=model)
    return charged


def debit_images(user_id: int, count: int = 1) -> None:
    _manager().debit_plan_images(user_id, count)


def assert_can_generate_image(user_id: int) -> None:
    sub = _manager().get_subscription(user_id)
    view = usage_view(sub)
    if view["unlimited"]:
        return
    remaining = view["images"]["remaining"]
    if remaining is not None and remaining <= 0:
        raise QuotaError("Картинки на этот месяц закончились.", "quota")
