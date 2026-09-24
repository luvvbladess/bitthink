"""Редактор документов: открытие, сохранения от OnlyOffice и ИИ-правка фрагмента."""

import io

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.config import get_settings
from app.bot_core.db_conversations import DatabaseConversationManager


def _docx(text: str) -> bytes:
    from docx import Document

    document = Document()
    document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def editor(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ONLYOFFICE_JWT_SECRET", "ds-secret")
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(settings, "ONLYOFFICE_PUBLIC_URL", "https://site.example/onlyoffice")
    monkeypatch.setattr(settings, "ONLYOFFICE_INTERNAL_URL", "http://onlyoffice")
    from app.api import editor as module

    return module


def _room_with_contract(settings, owner: int, guest: int):
    manager = DatabaseConversationManager()
    conv = manager.create_conversation(owner, title="Договор")
    stored = settings.UPLOAD_DIR / "generated" / "abcdef0123456789" / ("0" * 32 + ".docx")
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(_docx("Срок оплаты 30 дней."))
    manager.add_message(
        owner, "assistant", "Готово", conv_id=conv.id,
        attachment={"name": "Договор.docx", "status": "done", "type": "generated",
                    "url": f"/uploads/generated/abcdef0123456789/{'0' * 32}.docx"},
    )
    token = manager.create_share(owner, conv.id)
    manager.join_share(guest, token)
    return manager, manager.conversation_view(owner, conv.id)


def test_members_share_one_document_and_saves_version_it(editor):
    settings = get_settings()
    manager, conv = _room_with_contract(settings, 881_001, 881_002)
    guest_view = manager.conversation_view(881_002, conv.id)

    first = editor._open_record(conv.id, "Договор.docx", 881_001, lambda: editor.source_bytes(conv, "Договор.docx"))
    second = editor._open_record(guest_view.id, "Договор.docx", 881_002, lambda: editor.source_bytes(guest_view, "Договор.docx"))
    assert first == second  # тот же key – совместная правка вживую
    doc_id, version = first
    assert version == 1 and editor.version_path(doc_id, 1).is_file()

    # Принудительное сохранение не рвёт живую сессию: версия та же.
    assert editor.store_saved_version(doc_id, _docx("Срок оплаты 10 дней."), bump=False) == 1
    # Все закрыли документ – следующее открытие получит новый key.
    assert editor.store_saved_version(doc_id, _docx("Срок оплаты 10 рабочих дней."), bump=True) == 2
    assert editor._open_record(conv.id, "Договор.docx", 881_001, lambda: None) == (doc_id, 2)
    # Чат видит исправленный текст.
    docs = manager.get_documents(881_001, conv_id=conv.id)
    assert any("10 рабочих дней" in item["content"] for item in docs)

    manager.delete_conversation(881_001, conv.id)


def test_callback_requires_document_server_signature(editor):
    settings = get_settings()
    manager, conv = _room_with_contract(settings, 881_011, 881_012)
    doc_id, _ = editor._open_record(conv.id, "Договор.docx", 881_011, lambda: editor.source_bytes(conv, "Договор.docx"))
    from app.main import app

    client = TestClient(app)
    link = editor.sign_link(doc_id, "callback")
    body = {"status": 1, "key": f"{doc_id}-1"}
    assert client.post(f"/editor/{doc_id}/callback?t={link}", json=body).status_code == 403
    signed = {"token": jwt.encode(body, "ds-secret", algorithm="HS256")}
    assert client.post(f"/editor/{doc_id}/callback?t={link}", json=signed).json() == {"error": 0}
    # Чужая ссылка (от файла) не подходит к колбэку.
    wrong = editor.sign_link(doc_id, "file")
    assert client.post(f"/editor/{doc_id}/callback?t={wrong}", json=signed).status_code == 403
    manager.delete_conversation(881_011, conv.id)


def test_saved_file_is_fetched_only_from_internal_document_server(editor):
    assert (
        editor.internal_download_url("https://site.example/onlyoffice/cache/files/data/key/output.docx?md5=x")
        == "http://onlyoffice/cache/files/data/key/output.docx?md5=x"
    )
    assert editor.internal_download_url("http://169.254.169.254/latest/meta-data") == "http://onlyoffice/latest/meta-data"


def test_ai_edit_needs_document_token_and_room_access(editor, monkeypatch):
    settings = get_settings()
    manager, conv = _room_with_contract(settings, 881_021, 881_022)
    doc_id, _ = editor._open_record(conv.id, "Договор.docx", 881_021, lambda: editor.source_bytes(conv, "Договор.docx"))
    seen = {}

    async def fake_chat(messages, **kwargs):
        seen["prompt"] = messages[-1]["content"]
        return "«Срок оплаты – 10 рабочих дней.»", [], "", []

    import openai_client

    monkeypatch.setattr(openai_client, "get_chat_response", fake_chat)
    from app.main import app

    client = TestClient(app)
    payload = {"selection": "Срок оплаты 30 дней.", "instruction": "сделай 10 рабочих дней"}
    guest_token = editor.sign_link(doc_id, "ai", user=881_022)
    ok = client.post(f"/editor/{doc_id}/ai", json=payload, headers={"Authorization": f"Bearer {guest_token}"})
    assert ok.status_code == 200, ok.text
    assert ok.json() == {"text": "Срок оплаты – 10 рабочих дней."}
    assert "Срок оплаты 30 дней." in seen["prompt"] and "сделай 10 рабочих дней" in seen["prompt"]

    stranger = editor.sign_link(doc_id, "ai", user=881_099)
    assert client.post(f"/editor/{doc_id}/ai", json=payload, headers={"Authorization": f"Bearer {stranger}"}).status_code == 403
    file_link = editor.sign_link(doc_id, "file", user=881_022)
    assert client.post(f"/editor/{doc_id}/ai", json=payload, headers={"Authorization": f"Bearer {file_link}"}).status_code == 403
    manager.delete_conversation(881_021, conv.id)
