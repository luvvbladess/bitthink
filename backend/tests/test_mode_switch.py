import asyncio
import json
import os

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-key")
os.environ.setdefault("KIMI_API_KEY", "test-key")

from app.config import get_settings  # noqa: F401 — puts bot_core on sys.path
from mode_switch import MODE_SWITCH_QUERY, pack_mode_switch, suggest_mode_switch

PRO = {"auto", "kimi-k2.6", "gpt-6-luna", "director", "studio", "gpt-6-sol"}
CREATOR = PRO | {"docgen", "gpt-6-astra"}


def test_studio_request_in_chat_suggests_studio():
    suggestion = suggest_mode_switch("auto", "Собери презентацию запуска кофейни на 8 слайдов", allowed=PRO)
    assert suggestion is not None
    assert suggestion["model"] == "studio"
    assert suggestion["accept"] == "Перейти в Студию"
    packed = pack_mode_switch(suggestion)
    assert packed[0]["query"] == MODE_SWITCH_QUERY
    assert json.loads(packed[0]["summary"])["model"] == "studio"


def test_current_mode_that_can_build_slides_is_not_blocked():
    ask = "Собери презентацию запуска кофейни на 8 слайдов"
    assert suggest_mode_switch("studio", ask, allowed=PRO) is None
    assert suggest_mode_switch("director", ask, allowed=PRO) is None
    assert suggest_mode_switch("gpt-6-astra", ask, allowed=CREATOR) is None


def test_analyzing_a_deck_stays_in_chat():
    assert suggest_mode_switch("auto", "Проанализируй презентацию и скажи, что поправить", allowed=PRO) is None


def test_mail_and_server_suggest_pilot_only_when_missing():
    ask = "Проверь непрочитанные письма в Gmail и скажи, что требует ответа"
    suggestion = suggest_mode_switch("studio", ask, allowed=PRO)
    assert suggestion is not None and suggestion["model"] == "director"
    assert suggest_mode_switch("director", ask, allowed=PRO) is None
    assert suggest_mode_switch("gpt-6-astra", ask, allowed=CREATOR) is None
    assert suggest_mode_switch("auto", "Зайди на сервер по ssh и выполни команду df", allowed=PRO)["model"] == "director"


def test_writing_a_letter_is_not_a_pilot_task():
    assert suggest_mode_switch("auto", "Напиши официальное письмо клиенту о переносе срока", allowed=PRO) is None


def test_template_document_suggests_docgen_when_the_plan_has_it():
    ask = "Собери документ по шаблону из прикреплённых файлов. Остальные файлы — база знаний."
    assert suggest_mode_switch("studio", ask, allowed=CREATOR)["model"] == "docgen"
    assert suggest_mode_switch("docgen", ask, allowed=CREATOR) is None
    assert suggest_mode_switch("studio", ask, allowed=PRO) is None


def test_plain_document_question_stays_put():
    assert suggest_mode_switch("auto", "Проанализируй документ и выпиши сроки", allowed=CREATOR) is None
    assert suggest_mode_switch("auto", "Напиши короткий договор на одну страницу", allowed=CREATOR) is None


def test_web_question_in_studio_suggests_search_not_in_chat():
    ask = "Что сегодня произошло в мире? Коротко и по источникам."
    suggestion = suggest_mode_switch("studio", ask, allowed=PRO)
    assert suggestion is not None and suggestion["model"] == "kimi-k2.6"
    assert suggest_mode_switch("docgen", ask, allowed=CREATOR)["model"] == "kimi-k2.6"
    assert suggest_mode_switch("auto", ask, allowed=PRO) is None
    assert suggest_mode_switch("kimi-k2.6", ask, allowed=PRO) is None
    assert suggest_mode_switch("director", ask, allowed=PRO) is None


def test_locked_mode_is_not_offered():
    free = {"auto", "kimi-k2.6", "gpt-5-nano", "gpt-6-luna"}
    assert suggest_mode_switch("auto", "Собери презентацию на 6 слайдов", allowed=free) is None


def test_get_smart_response_returns_suggestion_without_calling_the_model(monkeypatch):
    from handlers import core as core_mod

    monkeypatch.setattr(core_mod.conversation_manager, "get_user_model", lambda _uid: "auto")
    monkeypatch.setattr(core_mod.conversation_manager, "get_user_reasoning_effort", lambda _uid: "none")
    monkeypatch.setattr(core_mod.conversation_manager, "get_subscription", lambda _uid: {"tier": "pro"})

    def boom(*_args, **_kwargs):
        raise AssertionError("model must not run")

    monkeypatch.setattr(core_mod, "get_chat_response", boom)
    answer, files, reasoning, search = asyncio.run(
        core_mod.get_smart_response(7, "Собери инфографику пути зерна от фермы до чашки", [], None)
    )
    assert "Студия" in answer
    assert files == []
    assert reasoning == ""
    assert search[0]["query"] == MODE_SWITCH_QUERY
    assert json.loads(search[0]["summary"])["model"] == "studio"
