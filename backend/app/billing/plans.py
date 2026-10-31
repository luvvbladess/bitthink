"""Bit-Think token plans: one unit = one Luna token."""

from __future__ import annotations

from typing import Any

LONG_CONTEXT_INPUT = 272_000
# Cached prompt *hits* cost us ~10% of input. Charge a quarter so the pool
# lasts longer without going below API cost. Cache *writes* are billed higher.
CACHED_INPUT_FRACTION = 0.25
CACHE_WRITE_FRACTION = 1.25

# 1 our-token = 1 GPT-6 Luna blended token. Rounded up so a full pool stays
# in the black. The multiplier is the list-price ratio to Luna ($0.10 in /
# $0.50 out), checked October 2026:
#   Sol 6.1   $2 / $10      = 20x   Astra $10 / $50   = 100x
#   Kimi K2.6 $0.95 / $4    ~  9x   DeepSeek Pro (peak/off-peak mix) ~ 9x, Flash ~ 2x
#   Haiku 5.5 $0.10 / $0.50 = 1x    Sonnet 5.5 $2 / $10 = 20x   Opus 5.5 $4 / $20 = 40x
# Haiku's whole request jumps 5x once the prompt exceeds 100k tokens. That
# step replaces the generic 2x long-context factor; the two do not stack.
# Re-derive these whenever a vendor changes prices; the stale 4x for Kimi and
# 5x for DeepSeek were charging users roughly half of what the calls cost us.
# Retired GPT-5.6 ids stay priced so old usage rows still debit correctly.
MODEL_MULTIPLIER: dict[str, int] = {
    "gpt-5-nano": 1,
    "gpt-5.6-luna": 1,
    "gpt-6-luna": 1,
    "kimi-k2.6": 9,
    "deepseek-v4-pro": 9,
    "deepseek-v4-flash": 2,
    "gpt-5.6-terra": 13,
    "studio": 13,
    "gpt-5.6-sol": 32,
    "gpt-5.6-sol-pro": 32,
    "gpt-6-sol": 20,
    "gpt-6.1-terra": 10,
    "gpt-6-astra": 100,
    "claude-haiku-5.5": 1,
    "claude-sonnet-5.5": 20,
    "claude-opus-5.5": 40,
    "glm-5.3-flash": 1,
    "minimax-m3.1-flash": 2,
}

# Saved chats and in-flight requests may still name the previous generation.
LEGACY_MODEL_ALIASES = {
    "gpt-5.6-luna": "gpt-6-luna",
    "gpt-5.6-terra": "gpt-6-sol",
    "gpt-5.6-sol": "gpt-6-sol",
    "gpt-5.6-sol-pro": "gpt-6-sol",
}

# Usage must bill the product id even if a row keeps the provider slug.
PROVIDER_MODEL_ALIASES = {
    "anthropic/claude-haiku-5.5": "claude-haiku-5.5",
    "anthropic/claude-sonnet-5.5": "claude-sonnet-5.5",
    "anthropic/claude-opus-5.5": "claude-opus-5.5",
}
from app.services.model_registry import MODEL_ALIASES
PROVIDER_MODEL_ALIASES.update(MODEL_ALIASES)
HAIKU_TIER_INPUT = 100_000

CHEAP_MODELS = [
    "auto",
    "correspondent",
    "kimi-k2.6",
    "gpt-5-nano",
    "gpt-6-luna",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "claude-haiku-5.5",
]

PRO_MODELS = CHEAP_MODELS + ["director", "studio", "gpt-6-sol", "gpt-6.1-terra", "claude-sonnet-5.5"]
PROPLUS_MODELS = PRO_MODELS + ["gpt-6-astra", "claude-opus-5.5"]
ULTRA_MODELS = list(PROPLUS_MODELS)
# Creator is the internal unlimited seat. It must never lag behind Ultra.
# docgen (режим «Документы») is creator-only: a single run can take hours and
# generate thousands of model calls, so it stays off every paid, quota-bound tier.
CREATOR_MODELS = list(ULTRA_MODELS) + ["docgen"]


TIER_ALIASES = {
    "start": "pro",
    "max": "ultra",
}

CANONICAL_TIERS = ("free", "trial", "pro", "proplus", "ultra", "creator")

PLAN_CATALOG: dict[str, dict[str, Any]] = {
    "free": {
        "id": "free",
        "name": "Базовый",
        "price_rub": 0,
        "price_year_rub": 0,
        "description": "Знакомство с чатом",
        "chat_tokens": 0,
        "computer_tokens": 0,
        "images": 3,
        "models": ["auto", "kimi-k2.6", "gpt-5-nano", "gpt-6-luna", "claude-haiku-5.5"],
        "daily_replies": 30,
        "daily_searches": 15,
        "features": ["30 ответов в день, из них до 15 с поиском", "3 картинки в месяц", "без Оркестратора, Студии и Исследования"],
    },
    "trial": {
        "id": "trial",
        "name": "Пробный",
        "price_rub": 0,
        "price_year_rub": 0,
        "description": "Несколько дней Pro+",
        "chat_tokens": 81_000_000,
        "computer_tokens": 50_000_000,
        "chat_week": 20_250_000,
        "chat_session": 5_760_000,
        "computer_week": 12_500_000,
        "computer_session": 3_570_000,
        "images": 40,
        "models": list(PROPLUS_MODELS),
        "features": ["Как Pro+", "короткий срок"],
    },
    "pro": {
        "id": "pro",
        "name": "Pro",
        "price_rub": 1_990,
        "price_year_rub": 19_900,
        "description": "GPT-6.1 Sol, Исследование и Оркестратор",
        "chat_tokens": 45_000_000,
        "computer_tokens": 15_000_000,
        "chat_week": 11_250_000,
        "chat_session": 3_240_000,
        "computer_week": 3_750_000,
        "computer_session": 1_075_000,
        "images": 25,
        "models": list(PRO_MODELS),
        "features": ["GPT-6.1 Sol и Исследование", "Студия"],
    },
    "proplus": {
        "id": "proplus",
        "name": "Pro+",
        "price_rub": 3_990,
        "price_year_rub": 39_900,
        "description": "GPT-6 Astra и больше ресурсов для сложных задач",
        "chat_tokens": 81_000_000,
        "computer_tokens": 50_000_000,
        "chat_week": 20_250_000,
        "chat_session": 5_760_000,
        "computer_week": 12_500_000,
        "computer_session": 3_570_000,
        "images": 40,
        "models": list(PROPLUS_MODELS),
        "features": ["всё из Pro", "GPT-6 Astra"],
    },
    "ultra": {
        "id": "ultra",
        "name": "Ultra",
        "price_rub": 12_990,
        "price_year_rub": 129_900,
        "description": "Самая глубокая проработка",
        "chat_tokens": 270_000_000,
        "computer_tokens": 135_000_000,
        "chat_week": 67_500_000,
        "chat_session": 19_260_000,
        "computer_week": 33_750_000,
        "computer_session": 9_630_000,
        "images": 80,
        "models": list(ULTRA_MODELS),
        "features": ["всё из Pro+"],
    },
    "creator": {
        "id": "creator",
        "name": "Creator",
        "price_rub": 0,
        "price_year_rub": 0,
        "description": "Без лимитов, не продаётся",
        "chat_tokens": 0,
        "computer_tokens": 0,
        "images": 0,
        "models": list(CREATOR_MODELS),
        "unlimited": True,
        "features": ["без лимитов", "все возможности Ultra, включая GPT-6 Astra"],
    },
}

NANO_CUSHION_PER_DAY = 40
SESSION_SECONDS = 5 * 60 * 60
PUBLIC_PLAN_IDS = ("pro", "proplus", "ultra")

# Keep the original allocations for compatibility and accounting history.
# Enforcement and current clients use one shared budget. Existing per-mode
# counters are added, so no migration resets usage or invalidates reservations.
# Increased monthly/weekly allowances, approved 2026-10-16. Trial follows Pro+.
SHARED_LIMITS = {
    "pro": (75_000_000, 30_000_000),
    "proplus": (165_000_000, 65_500_000),
    "ultra": (510_000_000, 202_500_000),
    "trial": (165_000_000, 65_500_000),
}
for _tier in ("trial", "pro", "proplus", "ultra"):
    _plan = PLAN_CATALOG[_tier]
    _plan["shared_budget"] = True
    _plan["total_tokens"], _plan["weekly_tokens"] = SHARED_LIMITS[_tier]
    _plan["session_tokens"] = 2 * (_plan["chat_session"] + _plan["computer_session"])
    if _tier != "trial":
        _plan["features"] = [f'{_plan["total_tokens"] // 1_000_000} млн общих единиц в месяц',
            'Единый запас для чата, Оркестратора и Студии', 'Увеличенное окно на 5 часов',
            'Поиск в пределах общего запаса', *_plan['features'], f'{_plan["images"]} изображений в месяц']


def canonical_tier(tier: str | None) -> str:
    raw = (tier or "free").strip().lower()
    return TIER_ALIASES.get(raw, raw if raw in PLAN_CATALOG else "free")


def plan_for(tier: str | None) -> dict[str, Any]:
    return PLAN_CATALOG[canonical_tier(tier)]


def allowed_models(tier: str | None) -> set[str]:
    plan = plan_for(tier)
    allowed = set(plan["models"])
    if plan.get("unlimited") or "*" in allowed:
        allowed |= set(ULTRA_MODELS) | set(MODEL_MULTIPLIER) | {
            "auto",
            "correspondent",
            "director",
            "studio",
            "kimi-k2.6",
        }
        allowed.discard("*")
    return allowed


def _everyday_model(allowed: set[str]) -> str:
    if "gpt-6-luna" in allowed:
        return "gpt-6-luna"
    return "gpt-5-nano"


def clamp_model(tier: str | None, model: str) -> str:
    model = LEGACY_MODEL_ALIASES.get(model, model)
    allowed = allowed_models(tier)
    if model in allowed:
        return model
    if model in {"gpt-6-astra", "claude-opus-5.5", "claude-sonnet-5.5"} and "gpt-6-sol" in allowed:
        return "gpt-6-sol"
    if model == "gpt-6-sol":
        return _everyday_model(allowed)
    if model == "director" and "director" not in allowed:
        return _everyday_model(allowed)
    if model == "studio" and "studio" not in allowed:
        return _everyday_model(allowed)
    if model == "docgen" and "docgen" not in allowed:
        return _everyday_model(allowed)
    if model == "deepseek-v4-flash" and "deepseek-v4-pro" in allowed:
        return "deepseek-v4-flash"
    return _everyday_model(allowed)


def research_model(tier: str | None) -> str | None:
    allowed = allowed_models(tier)
    if "gpt-6-sol" in allowed:
        return "gpt-6-sol"
    return None


def computer_models(tier: str | None) -> list[str]:
    allowed = allowed_models(tier)
    pool = [item for item in ("gpt-5-nano", "gpt-6-luna", "kimi-k2.6", "claude-haiku-5.5", "deepseek-v4-pro") if item in allowed]
    if "gpt-6.1-terra" in allowed:
        pool.append("gpt-6.1-terra")
    if "gpt-6-sol" in allowed:
        pool.append("gpt-6-sol")
    if "claude-sonnet-5.5" in allowed:
        pool.append("claude-sonnet-5.5")
    if "claude-opus-5.5" in allowed:
        pool.append("claude-opus-5.5")
    if "gpt-6-astra" in allowed:
        pool.append("gpt-6-astra")
    if 'director' in allowed:
        from app.services.model_registry import experimental_workers, production_workers
        pool.extend(dict.fromkeys(production_workers() + experimental_workers()))
    return pool or ["gpt-6-luna"]


def canonical_billing_model(model: str) -> str:
    """Map a provider slug onto the product id. Retired GPT-5.6 ids keep their own rates."""
    return PROVIDER_MODEL_ALIASES.get(model or "", model or "")


def billed_multiplier(model: str, input_tokens: int = 0) -> int:
    """Plan units per blended token. Unknown models stay at 1x and are visible, not free."""
    model = canonical_billing_model(model)
    multiplier = MODEL_MULTIPLIER.get(model, 1)
    tokens = max(0, int(input_tokens or 0))
    if model == "claude-haiku-5.5" and tokens > HAIKU_TIER_INPUT:
        return multiplier * 5
    from app.services.model_registry import model_spec
    spec = model_spec(model)
    if tokens > LONG_CONTEXT_INPUT and ((spec is not None and spec.provider == 'openai') or model.startswith('gpt-5.')):
        return multiplier * 2
    return multiplier


def our_tokens(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_input_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> int:
    input_tokens = max(0, int(input_tokens or 0))
    output_tokens = max(0, int(output_tokens or 0))
    cached = min(max(0, int(cached_input_tokens or 0)), input_tokens)
    writes = min(max(0, int(cache_write_tokens or 0)), input_tokens - cached)
    fresh = input_tokens - cached - writes
    blended_input = (
        fresh
        + int(cached * CACHED_INPUT_FRACTION + 0.999)
        + int(writes * CACHE_WRITE_FRACTION + 0.999)
    )
    raw = blended_input + output_tokens
    if raw <= 0:
        return 0
    return max(1, raw * billed_multiplier(model, input_tokens))
