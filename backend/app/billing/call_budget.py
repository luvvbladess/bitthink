"""Preflight and atomically reserve every provider hop, including tool loops.

OpenAI uses its input-token counting endpoint. Text-only compatible APIs use
UTF-8 bytes plus message/schema overhead as a conservative uncached estimate.
Actual usage replaces the hold immediately; unspent units are returned. A
persistent hold expires after 15 minutes if a worker is killed mid-call.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

from app.billing.plans import billed_multiplier, our_tokens, plan_for
from app.billing.quota import (
    QuotaError, _manager, billing_pool, billing_user, effective_tier,
    raise_if_blocked, refresh_windows, release_paid_hold, usage_view,
)

logger = logging.getLogger(__name__)


def wallet_user(user_id: int | None) -> bool:
    if not user_id:
        return False
    tier = effective_tier(_manager().get_subscription(user_id))
    return tier != "free" and not plan_for(tier).get("unlimited")


def estimate_text_input(request: dict) -> int:
    """Byte ceiling, not the display/packing estimate (which divides by three)."""
    payload = {k: request[k] for k in ("input", "messages", "instructions", "tools") if k in request}
    model = str(request.get('model') or '')
    images = 0
    def scrub(value):
        nonlocal images
        if isinstance(value, dict):
            if value.get('type') in {'image_url', 'input_image'} and ('claude-' in model):
                images += 1
                return {'type': 'image_url', 'image_url': {'url': '<visual tokens counted separately>'}}
            return {key: scrub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [scrub(item) for item in value]
        return value
    payload = scrub(payload)
    encoded = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    # Per-message protocol tokens and vendor tool wrappers.
    items = request.get("messages") or request.get("input") or []
    # Claude 4.7+ caps a downscaled image at 4,784 visual tokens. Reserve 5,000;
    # base64 bytes are transport, not millions of billable text tokens.
    return len(encoded) + 4096 + 64 * (len(items) if isinstance(items, list) else 1) + images * 5_000


def _refund(data: dict, row: Any, amount: int) -> None:
    if data.get("tier") != row.tier or int(data.get("expires_at") or 0) != row.subscription_expires_at:
        return
    keys = (
        (f"{row.pool}_tokens_used", "period_start", row.period_start),
        (f"week_{row.pool}_used", "week_start", row.week_start),
        (f"session_{row.pool}_used", "session_started_at", row.session_started_at),
    )
    for key, marker, expected in keys:
        if data.get(marker) == expected:
            data[key] = max(0, int(data.get(key) or 0) - amount)


def recover_expired(manager: Any, user_id: int) -> None:
    """Recover abandoned holds before the UI/precheck can report a full wallet."""
    from app.bot_core.db_conversations import _apply_subscription_payload, _subscription_payload
    from app.db.engine import SyncSessionLocal
    from app.db.models import TokenReservation
    with manager.transaction_lock, SyncSessionLocal() as session:
        sub = manager.lock_subscription(session, user_id)
        rows = session.query(TokenReservation).filter(
            TokenReservation.user_id == user_id, TokenReservation.expires_at <= int(time.time()),
        ).all()
        if rows:
            data = _subscription_payload(sub)
            refresh_windows(data)
            for row in rows:
                _refund(data, row, row.amount)
                session.delete(row)
            _apply_subscription_payload(sub, data)
            session.commit()


def reserve(user_id: int, pool: str, model: str, input_tokens: int, output_cap: int) -> tuple[str | None, int]:
    from app.bot_core.db_conversations import _apply_subscription_payload, _subscription_payload
    from app.db.engine import SyncSessionLocal
    from app.db.models import TokenReservation

    manager = _manager()
    with manager.transaction_lock, SyncSessionLocal() as session:
        sub = manager.lock_subscription(session, user_id)
        data = _subscription_payload(sub)
        refresh_windows(data)
        now = int(time.time())
        expired = session.query(TokenReservation).filter(
            TokenReservation.user_id == user_id, TokenReservation.expires_at <= now,
        ).all()
        for row in expired:
            _refund(data, row, row.amount)
            session.delete(row)
        tier = effective_tier(data)
        plan = plan_for(tier)
        if tier == "free" or plan.get("unlimited"):
            _apply_subscription_payload(sub, data)
            session.commit()
            return None, output_cap
        if not raise_if_blocked(data, pool, model):
            # The separately capped daily Nano cushion is not a paid wallet.
            return None, min(output_cap, 4000)
        if not data.get("session_started_at"):
            data["session_started_at"] = now
        keys = (f"{pool}_tokens_used", f"week_{pool}_used", f"session_{pool}_used")
        family = usage_view(data)['windows']['shared']
        remaining = min(int(family[kind]['remaining'] or 0) for kind in ('month', 'week', 'session'))
        # Assume all input is a cache write: real fresh/cache-hit usage refunds the difference.
        input_units = our_tokens(model, input_tokens, cache_write_tokens=input_tokens)
        factor = billed_multiplier(model, input_tokens)
        output_limit = min(output_cap, (remaining - input_units) // factor)
        if output_limit < 16:
            _apply_subscription_payload(sub, data)
            session.commit()
            raise QuotaError("Остатка лимита недостаточно для контекста и ответа. Сократите запрос или дождитесь обновления окна.")
        amount = input_units + output_limit * factor
        for key in keys:
            data[key] = int(data.get(key) or 0) + amount
        reservation_id = uuid.uuid4().hex
        session.add(TokenReservation(
            id=reservation_id, user_id=user_id, pool=pool, amount=amount, tier=data["tier"],
            subscription_expires_at=int(data.get("expires_at") or 0),
            period_start=data["period_start"], week_start=data["week_start"],
            session_started_at=data["session_started_at"], expires_at=now + 900,
        ))
        _apply_subscription_payload(sub, data)
        session.commit()
        return reservation_id, output_limit


def settle(user_id: int, reservation_id: str | None, actual: int | None, pool: str = "chat") -> None:
    if not reservation_id:
        return
    from app.bot_core.db_conversations import _apply_subscription_payload, _subscription_payload
    from app.db.engine import SyncSessionLocal
    from app.db.models import TokenReservation

    manager = _manager()
    with manager.transaction_lock, SyncSessionLocal() as session:
        sub = manager.lock_subscription(session, user_id)
        row = session.get(TokenReservation, reservation_id)
        if row is None:
            # A later call may have recovered a stale hold after a worker timeout.
            if actual:
                data = _subscription_payload(sub)
                refresh_windows(data)
                tier = effective_tier(data)
                if tier != "free" and not plan_for(tier).get("unlimited"):
                    if not data.get("session_started_at"):
                        data["session_started_at"] = int(time.time())
                    for key in (f"{pool}_tokens_used", f"week_{pool}_used", f"session_{pool}_used"):
                        data[key] = int(data.get(key) or 0) + actual
                _apply_subscription_payload(sub, data)
                session.commit()
            return
        data = _subscription_payload(sub)
        refresh_windows(data)
        if actual is not None:
            delta = row.amount - max(0, actual)
            if delta < 0:
                # Never hide a vendor/counting mismatch by clipping accounting.
                logger.error("Provider usage exceeded preflight hold: user=%s, units=%s", user_id, -delta)
            _refund(data, row, delta)
        session.delete(row)
        _apply_subscription_payload(sub, data)
        session.commit()


def token_counts(usage: Any) -> tuple[int, int, int, int]:
    def field(obj, key, default=0):
        return (obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)) or default
    inp = int(field(usage, "input_tokens", field(usage, "prompt_tokens")))
    out = int(field(usage, "output_tokens", field(usage, "completion_tokens")))
    details = field(usage, "input_tokens_details", field(usage, "prompt_tokens_details", {}))
    cached = int(field(usage, "prompt_cache_hit_tokens", field(usage, "cached_tokens", field(details, "cached_tokens"))))
    writes = int(field(details, "cache_write_tokens", field(details, "cache_creation_input_tokens",
                 field(details, "cache_creation_tokens", field(usage, "cache_creation_input_tokens")))))
    return inp, out, cached, writes


async def model_call(client: Any, request: dict, *, model: str, user_id: int | None = None,
                     responses: bool = False, consume=None, usage_is_result: bool = False,
                     timeout: int = 420, input_token_ceiling: int = 0):
    """Create one call and consume its stream inside the same reserved envelope."""
    user_id = user_id or billing_user.get()
    pool = billing_pool.get()
    pool = pool if pool in {"chat", "computer"} else "chat"
    request = dict(request)
    cap_key = "max_output_tokens" if responses else ("max_completion_tokens" if "max_completion_tokens" in request else "max_tokens")
    cap = int(request.get(cap_key) or 4000)
    reservation_id = None
    from app.services.orchestrator_budget import current_budget
    run_budget = current_budget.get()
    paid = await asyncio.to_thread(wallet_user, user_id)
    inp = 0
    if responses and (paid or run_budget is not None):
        count_params = {k: request[k] for k in ('model', 'input', 'instructions', 'tools', 'tool_choice', 'reasoning', 'text') if k in request}
        counted = await asyncio.wait_for(client.responses.input_tokens.count(**count_params), timeout=30)
        inp = int(counted.input_tokens)
    elif paid:
        inp = estimate_text_input(request)
    inp = max(inp, input_token_ceiling)
    if paid:
        release_paid_hold()
        pending = asyncio.create_task(asyncio.to_thread(reserve, user_id, pool, model, inp, cap))
        try:
            reservation_id, cap = await asyncio.shield(pending)
        except asyncio.CancelledError:
            # The DB thread can commit after the task is cancelled. Wait for its
            # receipt, then refund it, rather than stranding a 15-minute hold.
            reservation_id, _ = await pending
            await asyncio.shield(asyncio.to_thread(settle, user_id, reservation_id, 0, pool))
            raise
        request[cap_key] = cap
    create = client.responses.create if responses else client.chat.completions.create
    started = time.monotonic()
    usage = None
    completed = False
    run_hold = None
    try:
        if run_budget is not None:
            from app.services.model_registry import model_spec
            from app.services.orchestrator_metrics import phase
            spec = model_spec(model)
            run_output_cap = spec.output_cap if spec else int(request.get(cap_key) or cap)
            if phase.get() == 'planner':
                run_output_cap = min(run_output_cap, 4096)
            elif phase.get() == 'composer':
                run_output_cap = min(run_output_cap, 12_000)
            estimated_input = inp if paid or responses else max(estimate_text_input(request), input_token_ceiling)
            run_hold, run_cap = await run_budget.reserve_call(model, estimated_input, min(int(request.get(cap_key) or cap), run_output_cap))
            request[cap_key] = run_cap
        async def invoke():
            result = await create(**request)
            if not consume:
                return result
            try:
                return await consume(result)
            finally:
                if hasattr(result, "close"):
                    await result.close()
        result = await asyncio.wait_for(invoke(), timeout=timeout)
        completed = True
        usage = result if usage_is_result else getattr(result, "usage", None)
        if usage:
            counts = token_counts(usage)
            actual = our_tokens(model, *counts)
            await asyncio.to_thread(settle, user_id, reservation_id, actual, pool)
            reservation_id = None
            if user_id:
                from app.billing.costs import provider_cost_usd
                cost = provider_cost_usd(usage)
                extra = {'actual_usd': cost} if cost is not None else {}
                await asyncio.to_thread(_manager().track_tokens, user_id, model, *counts, debit=not paid, **extra)
        elif reservation_id:
            # A successful provider response without usage must not silently reopen the budget.
            logger.error("Provider returned no usage for user=%s model=%s; retaining maximum debit", user_id, model)
            await asyncio.to_thread(settle, user_id, reservation_id, None)
            reservation_id = None
        return result
    finally:
        try:
            if reservation_id:
                # Includes cancellation and provider failure. Refund only this call's hold.
                await asyncio.shield(asyncio.to_thread(settle, user_id, reservation_id, 0))
        finally:
            if run_budget is not None and run_hold is not None:
                run_budget.settle(run_hold, model, usage)
            from app.services.orchestrator_metrics import observe
            observe(model, usage, time.monotonic()-started, completed)
