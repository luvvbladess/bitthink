import asyncio


def test_legacy_search_checkpoint_respects_explicit_offline_mode(monkeypatch):
    import director_router
    import openai_client

    calls = []

    async def offline_response(*_args, **kwargs):
        calls.append(kwargs)
        return "Ответ по материалам проекта", [], "", []

    monkeypatch.setattr(openai_client, "get_chat_response", offline_response)
    result = asyncio.run(director_router._execute_employee(
        {"role": "analyst", "task": "Обобщи материалы проекта", "model": "kimi-k2.6", "web": False},
        1, [], 96303,
    ))

    assert result["status"] == "ok"
    assert calls[0]["model"] == director_router.FALLBACK_EMPLOYEE_MODEL
    assert calls[0]["force_web_search"] is False
