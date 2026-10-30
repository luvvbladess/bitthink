import asyncio
import sys
from types import ModuleType
import pytest

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


@pytest.mark.parametrize('conversion_failure', [False, True])
def test_long_reply_document_is_persisted_before_delivery(monkeypatch, conversion_failure):
    """The automatically created DOCX must be available to preview and reload."""
    saved, delivered = [], []
    async def response(*args, **kwargs):
        return 'Подробный ответ. ' * 600, [], '', []
    async def persist(*args, **kwargs):
        saved.append(kwargs)
    async def store(*args):
        return {'name': args[1], 'status': 'done', 'type': 'generated', 'url': '/uploads/generated/result.docx'}
    async def send_file(name, data):
        assert saved and saved[0]['attachment']['name'] == name
        delivered.append(name)
    async def noop(*args, **kwargs):
        return []
    handlers = ModuleType('handlers.core')
    handlers.get_smart_response = response
    handlers.sanitize_response_text = lambda text: text
    monkeypatch.setitem(sys.modules, 'handlers.core', handlers)
    import docx_generator
    def convert(*args):
        if conversion_failure:
            raise RuntimeError('Converter unavailable')
        return b'docx-bytes'
    monkeypatch.setattr(docx_generator, 'convert_markdown_to_docx', convert)
    monkeypatch.setattr(chat_service.repo.templates, 'base', lambda *args: None)
    monkeypatch.setattr(chat_service.repo, 'add_message', persist)
    monkeypatch.setattr(chat_service, '_persist_generated_file', store)
    monkeypatch.setattr(chat_service, 'schedule_memory_refresh', lambda *args: None)
    monkeypatch.setattr('app.services.sandbox_client.collect_workspace_files', noop)
    from app.services.desktop_context import desktop_mode
    token = desktop_mode.set(None)
    try:
        asyncio.run(chat_service._generate_and_send(1, 'preview@example.com', 'Объясни тему', [], noop, noop, send_file, noop, noop))
    finally:
        desktop_mode.reset(token)
    if conversion_failure:
        assert delivered == []
        assert saved[0]['attachment'] is None
    else:
        assert delivered == ['response.docx']
        assert saved[0]['attachment']['url'].endswith('result.docx')


def test_message_to_a_deleted_chat_starts_a_new_one(monkeypatch):
    """A tab left open on a chat deleted elsewhere used to fail every message."""
    import asyncio

    from app.services import chat_service

    metas = []

    async def fake_generate(*_args, **_kwargs):
        return None

    async def send_meta(conv_id, replaces=None):
        metas.append((conv_id, replaces))

    async def noop(*_args, **_kwargs):
        return None

    monkeypatch.setattr(chat_service, "_generate_and_send", fake_generate)
    asyncio.run(chat_service.run_chat(
        "deleted-chat@example.ru", "привет", "conv_20990101_000000_deadbeef",
        noop, noop, noop, send_meta=send_meta,
    ))
    new_id, replaces = metas[0]
    assert replaces == "conv_20990101_000000_deadbeef" and new_id != replaces
    messages = asyncio.run(chat_service.repo.get_messages("deleted-chat@example.ru", new_id))
    assert [m["content"] for m in messages] == ["привет"]
