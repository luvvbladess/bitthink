import asyncio
import sys
from types import ModuleType

from app.services import chat_service


def test_answer_is_persisted_even_when_websocket_delivery_is_gone(monkeypatch):
    saved = []

    async def fake_smart_response(*_args, **_kwargs):
        return "Готовый ответ по документам.", [], "", []

    async def fake_add_message(*args, **kwargs):
        saved.append((args, kwargs))

    async def disconnected(*_args, **_kwargs):
        raise RuntimeError("socket closed")

    fake_handlers = ModuleType("handlers.core")
    fake_handlers.get_smart_response = fake_smart_response
    fake_handlers.sanitize_response_text = lambda text: text
    monkeypatch.setitem(sys.modules, "handlers.core", fake_handlers)
    monkeypatch.setattr(chat_service.repo, "add_message", fake_add_message)
    monkeypatch.setattr(chat_service, "schedule_memory_refresh", lambda *_args, **_kwargs: None)

    async def no_files(*_args, **_kwargs):
        return []

    monkeypatch.setattr("app.services.sandbox_client.collect_workspace_files", no_files)

    asyncio.run(chat_service._generate_and_send(
        1,
        "user@example.com",
        "уточняющий вопрос",
        [{"role": "user", "content": "уточняющий вопрос"}],
        disconnected,
        disconnected,
        disconnected,
        disconnected,
        disconnected,
    ))

    assert len(saved) == 1
    assert saved[0][0][1:3] == ("assistant", "Готовый ответ по документам.")
