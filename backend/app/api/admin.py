from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.core.repository import repo
from app.db.engine import get_db
from app.db.models import Conversation, CustomPrompt, Message, Subscription, UsageRecord, User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users")
async def list_users(
    q: Optional[str] = None,
    role: Optional[str] = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    stmt = select(User)
    if q:
        stmt = stmt.where(User.email.ilike(f"%{q}%"))
    if role:
        stmt = stmt.where(User.role == role)

    total_result = await session.execute(select(func.count()).select_from(stmt.subquery()))
    total = total_result.scalar_one()

    stmt = stmt.order_by(User.created_at.desc()).offset(offset).limit(limit)
    result = await session.execute(stmt)
    users = result.scalars().all()

    bot_ids = [u.bot_user_id for u in users]
    subs: dict[int, Subscription] = {}
    if bot_ids:
        sub_rows = await session.execute(select(Subscription).where(Subscription.user_id.in_(bot_ids)))
        subs = {row.user_id: row for row in sub_rows.scalars().all()}

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": [
            {
                "id": u.id,
                "email": u.email,
                "first_name": u.first_name,
                "role": u.role,
                "bot_user_id": u.bot_user_id,
                "created_at": u.created_at.isoformat() if u.created_at else None,
                "tier": subs[u.bot_user_id].tier if u.bot_user_id in subs else "free",
                "expires_at": subs[u.bot_user_id].expires_at if u.bot_user_id in subs else 0,
            }
            for u in users
        ],
    }


@router.get("/users/{user_id}")
async def get_user(
    user_id: int,
    session: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    from app.api.billing import subscription_payload_for_bot

    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "role": user.role,
        "bot_user_id": user.bot_user_id,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "subscription": await subscription_payload_for_bot(user.bot_user_id),
    }


@router.get("/users/{user_id}/conversations")
async def get_user_conversations(
    user_id: int,
    session: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    conversations = await repo.get_conversations(user.email)
    return {"items": conversations}


@router.get("/users/{user_id}/messages")
async def get_user_messages(
    user_id: int,
    conversation_id: str,
    session: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    messages = await repo.get_messages(user.email, conversation_id)
    return {"items": messages}


@router.get("/users/{user_id}/usage")
async def get_user_usage(
    user_id: int,
    session: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    day = await repo.get_day_usage(user.email)
    month = await repo.get_month_usage(user.email)
    return {"day": day, "month": month}


@router.post("/users/{user_id}/subscription")
async def set_user_subscription(
    user_id: int,
    data: dict,
    session: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    tier = data.get("tier", "free")
    from app.billing.plans import CANONICAL_TIERS, TIER_ALIASES, canonical_tier

    if tier not in CANONICAL_TIERS and tier not in TIER_ALIASES:
        raise HTTPException(status_code=400, detail="Unknown tier")
    tier = canonical_tier(tier)
    try:
        duration_days = int(data.get("duration_days", 30))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid duration_days")
    if duration_days < 1:
        duration_days = 1
    from_today = bool(data.get("from_today", True))
    import asyncio

    bot_ids = {int(user.bot_user_id), repo._bot_id(user.email)}
    for bot_id in bot_ids:
        await asyncio.to_thread(
            repo._manager.set_subscription_tier, bot_id, tier, duration_days, from_today
        )
    return {"ok": True, "tier": tier, "from_today": from_today}


@router.post("/subscriptions/reset-non-admins")
async def reset_non_admin_subscriptions(
    data: Optional[dict] = Body(default=None),
    _: str = Depends(require_admin),
):
    from app.billing.plans import CANONICAL_TIERS, TIER_ALIASES, canonical_tier

    payload = data or {}
    tier = payload.get("tier", "free")
    if tier not in CANONICAL_TIERS and tier not in TIER_ALIASES:
        raise HTTPException(status_code=400, detail="Unknown tier")
    tier = canonical_tier(tier)
    try:
        duration_days = int(payload.get("duration_days", 30))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid duration_days")
    if duration_days < 1:
        duration_days = 1
    result = await repo.reset_non_admin_subscriptions(tier, duration_days)
    return {"ok": True, **result}


@router.post("/users/{user_id}/role")
async def set_user_role(
    user_id: int,
    data: dict,
    session: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    role = data.get("role")
    if role not in ("user", "admin"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")

    user.role = role
    await session.commit()
    return {"ok": True, "role": role}


@router.delete("/users/{user_id}/conversations/{conversation_id}")
async def delete_user_conversation(
    user_id: int,
    conversation_id: str,
    session: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    ok = await repo.delete_conversation(user.email, conversation_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return {"ok": True}


@router.get("/stats")
async def get_stats(
    session: AsyncSession = Depends(get_db),
    _: str = Depends(require_admin),
):
    total_users = (await session.execute(select(func.count()).select_from(User))).scalar_one()
    total_conversations = (await session.execute(select(func.count()).select_from(Conversation))).scalar_one()
    total_messages = (await session.execute(select(func.count()).select_from(Message))).scalar_one()
    return {
        "total_users": total_users,
        "total_conversations": total_conversations,
        "total_messages": total_messages,
    }
