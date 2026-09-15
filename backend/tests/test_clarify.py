import asyncio
import json

from app.config import get_settings  # noqa: F401
from clarify import is_clarify_reply, normalize_questions, pack_search, unpack_search
from director_router import _enforce_caps, _parse_director_plan


def test_normalize_questions_keeps_short_cards_and_drops_junk():
    questions = normalize_questions(
        [
            {
                "prompt": "Какой тип приложения ты хочешь создать?",
                "options": ["Веб-приложение", "Telegram-бот", "Другое", "Другое", "<script>"],
            },
            {"prompt": "x", "options": ["a", "b"]},
            {"prompt": "Какой стек взять для первой версии?", "options": ["Python", "Node"]},
        ]
    )
    assert len(questions) == 2
    assert questions[0]["options"] == ["Веб-приложение", "Telegram-бот", "Другое", "script"]
    assert unpack_search(pack_search(questions)) == questions


def test_parse_director_clarify_plan():
    plan = _parse_director_plan(
        '{"status":"clarify","questions":[{"prompt":"Какой тип приложения ты хочешь создать?","options":["Веб-приложение","Telegram-бот","CLI / скрипт"]}]}'
    )
    assert plan["status"] == "clarify"
    assert plan["new_employees"] == []
    assert plan["questions"][0]["options"][0] == "Веб-приложение"
    blocked = _enforce_caps(2, 0, plan)
    assert blocked["status"] == "done"


def test_clarify_reply_is_detected():
    assert is_clarify_reply("Уточнения по задаче:\n1. Тип – веб")
    assert is_clarify_reply("Уточнения пропущены. Действуй по здравому смыслу.")
    assert not is_clarify_reply("создай приложение")


def test_director_clarify_does_not_hire(monkeypatch):
    import director_router as dr

    async def fake_plan(_task, journal, _user_id, document_context="", history_text=""):
        assert journal == []
        return {
            "status": "clarify",
            "new_employees": [{"role": "X", "task": "should not run", "model": "gpt-5.6-luna"}],
            "questions": [
                {
                    "prompt": "Какой тип приложения ты хочешь создать?",
                    "options": ["Веб-приложение", "Telegram-бот", "Другое"],
                }
            ],
        }

    async def boom(*_args, **_kwargs):
        raise AssertionError("employees must not run on clarify")

    monkeypatch.setattr(dr, "_plan_round", fake_plan)
    monkeypatch.setattr(dr, "_execute_employee", boom)
    monkeypatch.setattr(dr, "_update_status", lambda *_args, **_kwargs: asyncio.sleep(0))

    answer, files, reasoning, search = asyncio.run(
        dr.get_director_response(
            [{"role": "user", "content": "создай приложение"}],
            "создай приложение",
            1,
            None,
        )
    )
    assert "тип приложения" in answer.lower()
    assert files == []
    assert reasoning == ""
    packed = unpack_search(search)
    assert packed and packed[0]["options"][1] == "Telegram-бот"
    assert json.loads(search[0]["summary"])["questions"]


def test_director_can_clarify_again_after_answers(monkeypatch):
    import director_router as dr

    async def fake_plan(task, journal, _user_id, document_context="", history_text=""):
        assert "Уточнения по задаче" in task
        assert journal == []
        return {
            "status": "clarify",
            "new_employees": [],
            "questions": [
                {
                    "prompt": "Какую идею реализовать в первой версии?",
                    "options": ["Ассистент", "Магазин", "Заявки", "Другое"],
                }
            ],
        }

    async def boom(*_args, **_kwargs):
        raise AssertionError("employees must not run on clarify")

    monkeypatch.setattr(dr, "_plan_round", fake_plan)
    monkeypatch.setattr(dr, "_execute_employee", boom)
    monkeypatch.setattr(dr, "_update_status", lambda *_args, **_kwargs: asyncio.sleep(0))

    answer, files, reasoning, search = asyncio.run(
        dr.get_director_response(
            [{"role": "user", "content": "Уточнения по задаче:\n1. Тип – Telegram-бот"}],
            "Уточнения по задаче:\n1. Тип – Telegram-бот",
            1,
            None,
        )
    )
    assert "идею" in answer.lower()
    assert files == []
    assert reasoning == ""
    packed = unpack_search(search)
    assert packed and packed[0]["options"][0] == "Ассистент"


def test_planner_prompt_allows_repeat_clarify():
    import director_router as dr
    import inspect

    source = inspect.getsource(dr._plan_round)
    assert "снова status=clarify" in source
    assert "clarify запрещён" not in source
