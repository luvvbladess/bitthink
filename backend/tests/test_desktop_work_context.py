from uuid import uuid4
from fastapi.testclient import TestClient
from app.main import app
from app.api import desktop
from app.auth import create_access_token_for_user
from app.db.engine import SyncSessionLocal
from app.db.models import User
from app.core.repository import repo
from app.services.desktop_context import desktop_work_context, desktop_mode


def test_context_separate_from_request_and_scoped(monkeypatch):
    email = f"desktop-context-{uuid4().hex}@example.com"
    with SyncSessionLocal() as db:
        db.add(User(email=email, password_hash="test-only", role="user", bot_user_id=repo._bot_id(email)))
        db.commit()
    seen = []
    async def local(user, content, cid, status, chunk, file, **kwargs):
        seen.append((content, desktop_work_context.get(), kwargs["history"]))
        assert desktop_mode.get() == "director"
        await chunk("checked")
    async def subscription(user): return {"name": "Pro"}
    monkeypatch.setattr(desktop, "run_local_chat", local)
    monkeypatch.setattr(desktop, "subscription_payload", subscription)
    with TestClient(app).websocket_connect("/desktop/ws") as ws:
        ws.send_json({"type": "auth", "payload": {"token": create_access_token_for_user(email, "user")}})
        assert ws.receive_json()["payload"]["work_context"] is True
        for policy in ["Правила проекта: DOCX XLSX PDF — не создавать без запроса", ""]:
            ws.send_json({"type": "run", "payload": {"content": "Изучи функцию", "cwd": "C:\\project", "history": [{"role": "user", "content": "Изучи функцию"}], "work_context": policy}})
            assert ws.receive_json()["type"] == "text"
            assert ws.receive_json()["type"] == "done"
        ws.send_json({"type": "run", "payload": {"content": "test", "work_context": "x" * 100001}})
        assert ws.receive_json()["type"] == "error"
        assert ws.receive_json()["type"] == "done"
    assert len(seen) == 2 and seen[0][0] == seen[1][0] == "Изучи функцию"
    assert seen[0][1].startswith("Правила") and seen[1][1] == ""
    assert all(item[2] == [{"role": "user", "content": "Изучи функцию"}] for item in seen)
    assert desktop_work_context.get() == ""


def test_context_not_available_to_website_or_ordinary_chat():
    from app.bot_core.director_router import _desktop_work_instructions, _wants_file
    token = desktop_work_context.set("создай PDF")
    try:
        assert _desktop_work_instructions() == ""
        mode = desktop_mode.set("chat")
        try: assert _desktop_work_instructions() == ""
        finally: desktop_mode.reset(mode)
        mode = desktop_mode.set("director")
        try:
            assert _desktop_work_instructions() == "создай PDF"
            assert not _wants_file("привет")
        finally: desktop_mode.reset(mode)
    finally: desktop_work_context.reset(token)
