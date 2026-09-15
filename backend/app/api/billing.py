from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.billing.costs import spend_summary
from app.billing.plans import PLAN_CATALOG, PUBLIC_PLAN_IDS, TIER_ALIASES
from app.billing.quota import usage_view
from app.core.repository import repo


async def subscription_view_from_sub(sub: dict, *, day=None, month=None) -> dict:
    view = usage_view(sub)
    view.update({
        "daily_nano_mini": sub.get("daily_nano_mini", 0),
        "daily_gpt54": sub.get("daily_gpt54", 0),
        "daily_director": sub.get("daily_director", 0),
        "daily_images": sub.get("daily_images", 0),
        "daily_docs": sub.get("daily_docs", 0),
        "last_reset_date": sub.get("last_reset_date", ""),
        "active_promocode": sub.get("active_promocode"),
    })
    if view.get("unlimited"):
        view["spend"] = {
            "currency": "USD",
            "day": spend_summary(day or {}),
            "month": spend_summary(month or {}),
        }
    return view


async def subscription_payload(user_id: str) -> dict:
    sub = await repo.get_subscription(user_id)
    from app.billing.plans import plan_for
    day = month = None
    if plan_for(sub.get("tier")).get("unlimited"):
        day = await repo.get_day_usage(user_id)
        month = await repo.get_month_usage(user_id)
    return await subscription_view_from_sub(sub, day=day, month=month)


async def subscription_payload_for_bot(bot_id: int) -> dict:
    import asyncio

    sub = await asyncio.to_thread(repo._manager.get_subscription, bot_id)
    day = month = None
    from app.billing.plans import plan_for
    if plan_for(sub.get("tier")).get("unlimited"):
        day = await asyncio.to_thread(repo._manager.get_day_usage, bot_id)
        month = await asyncio.to_thread(repo._manager.get_month_usage, bot_id)
    return await subscription_view_from_sub(sub, day=day, month=month)

router = APIRouter()


def _public_plans() -> list[dict]:
    plans = []
    for plan_id in PUBLIC_PLAN_IDS:
        plan = PLAN_CATALOG[plan_id]
        plans.append({
            "id": plan["id"],
            "name": plan["name"],
            "price_rub": plan["price_rub"],
            "price_year_rub": plan["price_year_rub"],
            "price_stars": 0,
            "duration_days": 30,
            "description": plan["description"],
            "features": plan["features"],
            "chat_tokens": plan["chat_tokens"],
            "computer_tokens": plan["computer_tokens"],
            "chat_week": plan.get("chat_week", 0),
            "chat_session": plan.get("chat_session", 0),
            "computer_week": plan.get("computer_week", 0),
            "computer_session": plan.get("computer_session", 0),
            "images": plan["images"],
        })
    return plans


KNOWN_PAY_PLANS = set(PLAN_CATALOG) | set(TIER_ALIASES) | set(PUBLIC_PLAN_IDS)


@router.get("/subscription")
async def get_subscription(user_id: str = Depends(get_current_user)):
    return await subscription_payload(user_id)


@router.get("/plans")
async def list_plans(user_id: str = Depends(get_current_user)):
    return {"plans": _public_plans()}


@router.post("/promocode")
async def apply_promocode(data: dict, user_id: str = Depends(get_current_user)):
    code = data.get("code", "").strip().upper()
    if code != "АПГ":
        raise HTTPException(status_code=400, detail="Invalid promocode")
    await repo.set_active_promocode(user_id, code)
    return {"ok": True, "discount_percent": 50}


@router.post("/payment/{plan}")
async def initiate_payment(plan: str, user_id: str = Depends(get_current_user)):
    """Online payment is not wired yet. Plans stay informational until checkout ships."""
    if plan not in KNOWN_PAY_PLANS:
        raise HTTPException(status_code=400, detail="Unknown plan")
    raise HTTPException(
        status_code=503,
        detail="Оплата скоро появится. Пока тариф выдаёт администратор.",
    )

