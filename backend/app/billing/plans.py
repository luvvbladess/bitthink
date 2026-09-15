"""Bit-Think token plans: one unit = one Luna token."""

from __future__ import annotations

from typing import Any

LONG_CONTEXT_INPUT = 272_000
# Cached prompt *hits* cost us ~10% of input. Charge a quarter so the pool
# lasts longer without going below API cost. Cache *writes* are billed higher.
CACHED_INPUT_FRACTION = 0.25
CACHE_WRITE_FRACTION = 1.25

# 1 our-token = 1 Luna blended token. Rounded up so a full pool stays in the black.
MODEL_MULTIPLIER: dict[str, int] = {
    "gpt-5-nano": 1,
    "gpt-5.6-luna": 1,
    "kimi-k2.6": 4,
    "deepseek-v4-pro": 5,
    "deepseek-v4-flash": 1,
    "gpt-5.6-terra": 13,
    "studio": 13,
    "gpt-5.6-sol": 32,
    "gpt-5.6-sol-pro": 32,
    "gpt-6-astra": 90,
}

CHEAP_MODELS = [
    "auto",
    "correspondent",
    "kimi-k2.6",
    "gpt-5-nano",
    "gpt-5.6-luna",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
]

PRO_MODELS = CHEAP_MODELS + ["director", "studio", "docgen"]
PROPLUS_MODELS = PRO_MODELS + ["gpt-5.6-terra"]
ULTRA_MODELS = PROPLUS_MODELS + ["gpt-5.6-sol", "gpt-5.6-sol-pro", "gpt-6-astra"]
# Creator is the internal unlimited seat. It must never lag behind Ultra.
CREATOR_MODELS = list(ULTRA_MODELS)


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
        "models": ["auto", "kimi-k2.6", "gpt-5-nano", "gpt-5.6-luna"],
        "daily_replies": 30,
        "daily_searches": 5,
        "features": ["30 ответов в день", "5 поисков в день", "3 картинки в месяц", "без Пилота, Студии и Исследования"],
    },
    "trial": {
        "id": "trial",
        "name": "Пробный",
        "price_rub": 0,
        "price_year_rub": 0,
        "description": "Несколько дней Pro+",
        "chat_tokens": 54_000_000,
        "computer_tokens": 26_400_000,
        "chat_week": 13_500_000,
        "chat_session": 3_840_000,
        "computer_week": 6_600_000,
        "computer_session": 1_884_000,
        "images": 40,
        "models": list(PROPLUS_MODELS),
        "features": ["Как Pro+", "короткий срок"],
    },
    "pro": {
        "id": "pro",
        "name": "Pro",
        "price_rub": 1_990,
        "price_year_rub": 19_900,
        "description": "Повседневный чат и Пилот",
        "chat_tokens": 30_000_000,
        "computer_tokens": 7_200_000,
        "chat_week": 7_500_000,
        "chat_session": 2_160_000,
        "computer_week": 1_800_000,
        "computer_session": 516_000,
        "images": 25,
        "models": list(PRO_MODELS),
        "features": ["окно 5 часов и неделя", "30 млн токенов в месяц", "7.2 млн на Пилот", "Студия и рабочие ответы"],
    },
    "proplus": {
        "id": "proplus",
        "name": "Pro+",
        "price_rub": 3_990,
        "price_year_rub": 39_900,
        "description": "Глубокий разбор сложных задач",
        "chat_tokens": 54_000_000,
        "computer_tokens": 26_400_000,
        "chat_week": 13_500_000,
        "chat_session": 3_840_000,
        "computer_week": 6_600_000,
        "computer_session": 1_884_000,
        "images": 40,
        "models": list(PROPLUS_MODELS),
        "features": ["окно 5 часов и неделя", "54 млн токенов в месяц", "глубокий разбор сложных задач"],
    },
    "ultra": {
        "id": "ultra",
        "name": "Ultra",
        "price_rub": 12_990,
        "price_year_rub": 129_900,
        "description": "Самая глубокая проработка",
        "chat_tokens": 180_000_000,
        "computer_tokens": 72_000_000,
        "chat_week": 45_000_000,
        "chat_session": 12_840_000,
        "computer_week": 18_000_000,
        "computer_session": 5_136_000,
        "images": 80,
        "models": list(ULTRA_MODELS),
        "features": ["окно 5 часов и неделя", "180 млн токенов в месяц", "GPT-6 Astra для самых сложных задач"],
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


def clamp_model(tier: str | None, model: str) -> str:
    allowed = allowed_models(tier)
    if model in allowed:
        return model
    if model == "gpt-5.6-sol-pro" and "gpt-5.6-sol" in allowed:
        return "gpt-5.6-sol"
    if model == "gpt-6-astra" and "gpt-5.6-sol" in allowed:
        return "gpt-5.6-sol"
    if model in {"gpt-5.6-sol", "gpt-5.6-sol-pro", "gpt-6-astra"} and "gpt-5.6-terra" in allowed:
        return "gpt-5.6-terra"
    if model == "gpt-5.6-terra":
        return "gpt-5.6-luna" if "gpt-5.6-luna" in allowed else "gpt-5-nano"
    if model == "director" and "director" not in allowed:
        return "gpt-5.6-luna"
    if model == "studio" and "studio" not in allowed:
        return "gpt-5.6-luna" if "gpt-5.6-luna" in allowed else "gpt-5-nano"
    if model == "docgen" and "docgen" not in allowed:
        return "gpt-5.6-luna" if "gpt-5.6-luna" in allowed else "gpt-5-nano"
    if model == "deepseek-v4-flash" and "deepseek-v4-pro" in allowed:
        return "deepseek-v4-flash"
    return "gpt-5.6-luna" if "gpt-5.6-luna" in allowed else "gpt-5-nano"


def research_model(tier: str | None) -> str | None:
    allowed = allowed_models(tier)
    if "gpt-5.6-sol" in allowed:
        return "gpt-5.6-sol"
    if "gpt-5.6-terra" in allowed:
        return "gpt-5.6-terra"
    return None


def computer_models(tier: str | None) -> list[str]:
    allowed = allowed_models(tier)
    pool = [item for item in ("gpt-5-nano", "gpt-5.6-luna", "kimi-k2.6", "deepseek-v4-pro") if item in allowed]
    if "gpt-5.6-terra" in allowed:
        pool.append("gpt-5.6-terra")
    if "gpt-5.6-sol" in allowed:
        pool.append("gpt-5.6-sol")
    if "gpt-6-astra" in allowed:
        pool.append("gpt-6-astra")
    return pool or ["gpt-5.6-luna"]


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
