from fastapi import APIRouter, Depends, HTTPException

import config as bot_config
from app.auth import get_current_user
from app.billing.plans import (
    LEGACY_MODEL_ALIASES,
    MODEL_MULTIPLIER,
    allowed_models,
    clamp_model,
    research_model,
)
from app.core.repository import repo
from app.models.schemas import ModelSelect

router = APIRouter()

# Web-only display layer: clean names + short descriptions for the picker UI.
WEB_MODEL_INFO = {
    "auto": {"name": "Лучший", "description": "Быстрый ответ или глубокий разбор — по переключателю"},
    "correspondent": {"name": "Официальный стиль", "description": "Деловая переписка и документы"},
    "director": {"name": "Пилот", "description": "Сам заходит на сайты, почту, VPS и сервисы"},
    "studio": {"name": "Студия", "description": "Картинки, слайды и инфографика на холсте"},
    "docgen": {"name": "Документы", "description": "Большой .docx по промпту и вашим файлам"},
    "kimi-k2.6": {"name": "Поиск в интернете", "description": "Актуальные данные и источники"},
    "gpt-5-nano": {"name": "Быстрый ответ (GPT-5 Nano)", "description": "Мгновенные ответы на простые вопросы"},
    "gpt-6-luna": {"name": "Быстрый", "description": "Повседневные вопросы пачками, с минимальным расходом"},
    "gpt-6-sol": {"name": "Эксперт", "description": "Сложный код, агенты и многошаговые задачи"},
    "gpt-6-astra": {"name": "Astra", "description": "Песочница GPT-6: код, договоры, файлы, многошаговые задачи"},
    "deepseek-v4-pro": {"name": "Код и логика", "description": "Программирование и технические задачи"},
}

# Perplexity-like public surface: users choose an intent, not a provider catalog.
# Hidden routes remain available internally to Auto, OCR and specialist pipelines.
PUBLIC_MODEL_IDS = ["auto", "gpt-6-luna", "gpt-6-sol", "gpt-6-astra", "director", "studio", "docgen"]

# The API lets Sol and Luna run up to max. The product dial keeps max on Astra
# so everyday Luna does not burn reasoning tokens, and xhigh on Sol and Astra.
REASONING_EFFORTS = ["none", "low", "medium", "high", "xhigh", "max"]
XHIGH_CAPABLE_MODELS = {"gpt-6-sol", "gpt-6-astra"}
MAX_CAPABLE_MODELS = {"gpt-6-astra"}

# Only the direct OpenAI-family models expose a real, honored effort dial in this
# integration. DeepSeek's reasoner and Kimi K2's thinking mode have no adjustable
# effort parameter in their APIs (reasoning is automatic/on-off, not tiered), and
# auto/correspondent/director are composite routes that pick per-step models and
# effort levels internally by design — a single global override would fight their
# own cost/quality routing logic. The picker is hidden for all of those.
REASONING_EFFORT_CAPABLE_MODELS = {
    "auto", "gpt-5-nano", "gpt-6-luna", "gpt-6-sol", "gpt-6-astra",
}


def _clamp_reasoning_effort(effort: str, model: str) -> str:
    if effort == "max" and model not in MAX_CAPABLE_MODELS:
        return "xhigh" if model in XHIGH_CAPABLE_MODELS else "high"
    if effort == "xhigh" and model not in XHIGH_CAPABLE_MODELS and model not in MAX_CAPABLE_MODELS:
        return "high"
    return effort


# Mirrors model availability by subscription tier
def _allowed_for(tier: str) -> set[str]:
    return allowed_models(tier)


@router.get("")
async def list_models(user_id: str = Depends(get_current_user)):
    subscription = await repo.get_subscription(user_id)
    tier = subscription.get("tier", "free")
    allowed = _allowed_for(tier)
    selected_model = await repo.get_user_model(user_id)
    clamped = clamp_model(tier, selected_model)
    if clamped != selected_model:
        await repo.set_user_model(user_id, clamped)
        selected_model = clamped
    reasoning_effort = await repo.get_user_reasoning_effort(user_id) or "none"
    reasoning_effort = _clamp_reasoning_effort(reasoning_effort, selected_model)
    research = research_model(tier)
    return {
        "models": [
            {
                "id": m,
                "name": WEB_MODEL_INFO.get(m, {}).get("name", n),
                "description": WEB_MODEL_INFO.get(m, {}).get("description", ""),
                "available": m in allowed,
                "multiplier": MODEL_MULTIPLIER.get(m, 1),
            }
            for m, n in bot_config.AVAILABLE_MODELS.items()
            if m in PUBLIC_MODEL_IDS
        ],
        "selected": selected_model,
        "reasoningEffort": reasoning_effort,
        "reasoningEfforts": REASONING_EFFORTS,
        "xhighCapable": selected_model in XHIGH_CAPABLE_MODELS or selected_model in MAX_CAPABLE_MODELS,
        "supportsReasoningEffort": selected_model in REASONING_EFFORT_CAPABLE_MODELS,
        "researchModel": research,
        "computerAvailable": "director" in allowed,
        "studioAvailable": "studio" in allowed,
        "docgenAvailable": "docgen" in allowed,
        "astraAvailable": "gpt-6-astra" in allowed,
        "multipliers": MODEL_MULTIPLIER,
    }


@router.post("/select")
async def select_model(data: ModelSelect, user_id: str = Depends(get_current_user)):
    requested = LEGACY_MODEL_ALIASES.get(data.model, data.model)
    if requested not in bot_config.AVAILABLE_MODELS:
        raise HTTPException(status_code=400, detail="Unknown model")
    subscription = await repo.get_subscription(user_id)
    allowed = _allowed_for(subscription.get("tier", "free"))
    if requested not in allowed:
        raise HTTPException(status_code=403, detail="Модель недоступна на этом тарифе")
    await repo.set_user_model(user_id, requested)
    return {"ok": True, "model": requested}


@router.post("/reasoning")
async def select_reasoning_effort(data: dict, user_id: str = Depends(get_current_user)):
    effort = data.get("effort")
    if effort not in REASONING_EFFORTS:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Unknown reasoning effort")
    model = await repo.get_user_model(user_id)
    clamped = _clamp_reasoning_effort(effort, model)
    await repo.set_user_reasoning_effort(user_id, clamped)
    return {"ok": True, "effort": clamped}


@router.get("/prompts")
async def list_prompts(user_id: str = Depends(get_current_user)):
    prompts = await repo.get_custom_prompts(user_id)
    active = await repo.get_active_custom_prompt(user_id)
    return {"prompts": prompts, "active": active}


@router.post("/prompts")
async def add_prompt(data: dict, user_id: str = Depends(get_current_user)):
    prompt = data.get("prompt", "").strip()
    if not prompt:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Empty prompt")
    index = await repo.add_custom_prompt(user_id, prompt)
    return {"ok": True, "index": index}


@router.delete("/prompts/{index}")
async def delete_prompt(index: int, user_id: str = Depends(get_current_user)):
    ok = await repo.delete_custom_prompt(user_id, index)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Prompt not found")
    return {"ok": True}


@router.post("/prompts/{index}/activate")
async def activate_prompt(index: int, user_id: str = Depends(get_current_user)):
    await repo.set_active_custom_prompt(user_id, index)
    return {"ok": True}
