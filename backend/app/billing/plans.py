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
    "gpt-6-astra": 100,
}

# Saved chats and in-flight requests may still name the previous generation.
LEGACY_MODEL_ALIASES = {
    "gpt-5.6-luna": "gpt-6-luna",
    "gpt-5.6-terra": "gpt-6-sol",
    "gpt-5.6-sol": "gpt-6-sol",
    "gpt-5.6-sol-pro": "gpt-6-sol",
}

CHEAP_MODELS = [
    "auto",
    "correspondent",
    "kimi-k2.6",
    "gpt-5-nano",
    "gpt-6-luna",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
]

PRO_MODELS = CHEAP_MODELS + ["director", "studio"]
PROPLUS_MODELS = PRO_MODELS + ["gpt-6-sol"]
ULTRA_MODELS = PROPLUS_MODELS + ["gpt-6-astra"]
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
        "models": ["auto", "kimi-k2.6", "gpt-5-nano", "gpt-6-luna"],
        "daily_replies": 30,
        "daily_searches": 5,
        "features": ["30 ответов в день", "5 поисков в день", "3 картинки в месяц", "без Оркестратора, Студии и Исследования"],
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
        "description": "Повседневный чат и Оркестратор",
        "chat_tokens": 45_000_000,
        "computer_tokens": 15_000_000,
        "chat_week": 11_250_000,
        "chat_session": 3_240_000,
        "computer_week": 3_750_000,
        "computer_session": 1_075_000,
        "images": 25,
        "models": list(PRO_MODELS),
        "features": ["окно 5 часов и неделя", "45 млн токенов в месяц", "15 млн на Оркестратор", "Студия и рабочие ответы"],
    },
    "proplus": {
        "id": "proplus",
        "name": "Pro+",
        "price_rub": 3_990,
        "price_year_rub": 39_900,
        "description": "GPT-6.1 Sol для сложных задач",
        "chat_tokens": 81_000_000,
        "computer_tokens": 50_000_000,
        "chat_week": 20_250_000,
        "chat_session": 5_760_000,
        "computer_week": 12_500_000,
        "computer_session": 3_570_000,
        "images": 40,
        "models": list(PROPLUS_MODELS),
        "features": ["окно 5 часов и неделя", "81 млн токенов в месяц", "50 млн на Оркестратор", "GPT-6.1 Sol для сложных задач"],
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
        "features": ["окно 5 часов и неделя", "270 млн токенов в месяц", "GPT-6 Astra для самых сложных задач"],
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
    if model == "gpt-6-astra" and "gpt-6-sol" in allowed:
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
    pool = [item for item in ("gpt-5-nano", "gpt-6-luna", "kimi-k2.6", "deepseek-v4-pro") if item in allowed]
    if "gpt-6-sol" in allowed:
        pool.append("gpt-6-sol")
    if "gpt-6-astra" in allowed:
        pool.append("gpt-6-astra")
    return pool or ["gpt-6-luna"]


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
    multiplier = MODEL_MULTIPLIER.get(model, 1)
    if input_tokens > LONG_CONTEXT_INPUT:
        multiplier *= 2
    return max(1, raw * multiplier)
