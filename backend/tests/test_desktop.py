import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from app.main import app
from app.api import desktop
from app.auth import create_access_token_for_user, create_refresh_token
from app.db.engine import SyncSessionLocal
from app.db.models import User
from app.services.desktop_context import desktop_executor, desktop_cwd, desktop_mode, desktop_chat_model, desktop_skills, local_skills_instructions
from app.services.sandbox_client import run_workspace_tool
from app.core.repository import repo


@pytest.fixture
def account():
    email = f"desktop-{uuid4().hex}@example.com"
    with SyncSessionLocal() as db:
        db.add(User(email=email, password_hash="test-only", role="user", bot_user_id=repo._bot_id(email)))
        db.commit()
    return email, create_access_token_for_user(email, "user")


def connect(client, token):
    ws = client.websocket_connect("/desktop/ws").__enter__()
    ws.send_json({"type": "auth", "payload": {"token": token}})
    assert ws.receive_json()["type"] == "ready"
    return ws


def test_desktop_requires_login():
    assert TestClient(app).get("/desktop/status").status_code == 401


def test_refresh_token_cannot_authenticate_desktop(account):
    email, _ = account
    with TestClient(app).websocket_connect("/desktop/ws") as ws:
        ws.send_json({"type": "auth", "payload": {"token": create_refresh_token({"sub": email})}})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_desktop_tools_and_history_roundtrip(monkeypatch, account):
    email, token = account
    async def fake_chat(user, content, cid, status, chunk, file, **kwargs):
        assert user == email
        assert content == "inspect project"
        assert desktop_cwd.get() == "C:\\project"
        result = await run_workspace_tool("workspace_ls", {}, 123)
        assert result == "file README.md"
        await chunk("Project checked")
    async def subscription(user):
        return {"name": "Pro", "computer": {"remaining": 999}}
    monkeypatch.setattr(desktop, "run_chat", fake_chat)
    monkeypatch.setattr(desktop, "run_local_chat", fake_chat)
    monkeypatch.setattr(desktop, "subscription_payload", subscription)
    with TestClient(app).websocket_connect("/desktop/ws") as ws:
        ws.send_json({"type": "auth", "payload": {"token": token}})
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "run", "payload": {"cwd": "C:\\project", "content": "inspect project"}})
        tool = ws.receive_json()
        assert tool["type"] == "tool_call"
        ws.send_json({"type": "tool_result", "payload": {"id": tool["payload"]["id"], "ok": True, "output": "file README.md"}})
        assert ws.receive_json()["payload"]["text"] == "Project checked"
        done = ws.receive_json()
        assert done["type"] == "done"
        assert done["payload"]["subscription"]["computer"]["remaining"] == 999
    assert desktop_executor.get() is None


def test_desktop_rejects_foreign_conversation(monkeypatch, account):
    email, token = account
    async def owner(cid):
        return -1
    monkeypatch.setattr(desktop.repo._manager, "conversation_owner", lambda cid: -1)
    with TestClient(app).websocket_connect("/desktop/ws") as ws:
        ws.send_json({"type": "auth", "payload": {"token": token}})
        ws.receive_json()
        ws.send_json({"type": "run", "payload": {"mode": "chat", "content": "inspect", "conversation_id": "someone-else"}})
        assert ws.receive_json()["type"] == "error"
        assert ws.receive_json()["type"] == "done"


def test_stop_cancels_pending_local_action(monkeypatch, account):
    _, token = account
    async def fake_chat(user, content, cid, status, chunk, file, **kwargs):
        await run_workspace_tool("workspace_write", {"path": "x.txt", "content": "test"}, 123)
        raise AssertionError("Cancelled task must not finish")
    monkeypatch.setattr(desktop, "run_chat", fake_chat)
    monkeypatch.setattr(desktop, "run_local_chat", fake_chat)
    with TestClient(app).websocket_connect("/desktop/ws") as ws:
        ws.send_json({"type": "auth", "payload": {"token": token}})
        ws.receive_json()
        ws.send_json({"type": "run", "payload": {"content": "write file"}})
        assert ws.receive_json()["type"] == "tool_call"
        ws.send_json({"type": "stop"})
        assert ws.receive_json()["type"] == "stopped"
        assert ws.receive_json()["type"] == "done"


def test_ordinary_chat_has_no_local_executor_and_streams_reasoning(monkeypatch, account):
    _, token = account
    async def fake_chat(user, content, cid, status, chunk, file, **kwargs):
        assert desktop_executor.get() is None
        assert desktop_cwd.get() == ""
        assert desktop_mode.get() == "chat"
        assert desktop_chat_model.get() == "auto"
        assert desktop_skills.get() == []
        await kwargs["send_reasoning_delta"]("Public reasoning")
        await chunk("Ordinary reply")
    monkeypatch.setattr(desktop, "run_chat", fake_chat)
    monkeypatch.setattr(desktop, "run_local_chat", fake_chat)
    with TestClient(app).websocket_connect("/desktop/ws") as ws:
        ws.send_json({"type": "auth", "payload": {"token": token}})
        assert "chat" in ws.receive_json()["payload"]["modes"]
        ws.send_json({"type": "run", "payload": {"mode": "chat", "content": "hello", "cwd": "C:\\ignored", "skills": [{"id": "local", "name": "must-not-load"}]}})
        assert ws.receive_json()["type"] == "conversation"
        assert ws.receive_json()["type"] == "reasoning_delta"
        assert ws.receive_json()["payload"]["text"] == "Ordinary reply"
        assert ws.receive_json()["type"] == "done"
    assert desktop_mode.get() is None
    assert desktop_executor.get() is None


def test_unknown_desktop_mode_rejected(account):
    _, token = account
    with TestClient(app).websocket_connect("/desktop/ws") as ws:
        ws.send_json({"type": "auth", "payload": {"token": token}})
        ws.receive_json()
        ws.send_json({"type": "run", "payload": {"mode": "invalid", "content": "hello"}})
        assert ws.receive_json()["type"] == "error"
        assert ws.receive_json()["type"] == "done"


def test_website_shared_member_can_continue_synced_chat(monkeypatch, account):
    _, token = account
    async def fake_chat(user, content, cid, status, chunk, file, **kwargs):
        assert cid == "shared-member"
        assert desktop_executor.get() is None
        await chunk("Shared reply")
    monkeypatch.setattr(desktop, "run_chat", fake_chat)
    monkeypatch.setattr(desktop.repo._manager, "conversation_owner", lambda cid: -1)
    monkeypatch.setattr(desktop.repo._manager, "conversation_roles", lambda user, ids: {"shared-member": "member"})
    with TestClient(app).websocket_connect("/desktop/ws") as ws:
        ws.send_json({"type": "auth", "payload": {"token": token}})
        ws.receive_json()
        ws.send_json({"type": "run", "payload": {"mode": "chat", "content": "hello", "conversation_id": "shared-member"}})
        assert ws.receive_json()["type"] == "conversation"
        assert ws.receive_json()["payload"]["text"] == "Shared reply"
        assert ws.receive_json()["type"] == "done"


def test_local_skills_catalog_and_resource_roundtrip(monkeypatch, account):
    _, token = account
    async def fake_chat(user, content, cid, status, chunk, file, **kwargs):
        from app.bot_core.computer_tools import run_computer_tool
        assert desktop_skills.get() == [{"id": "fixture", "name": "frontend-polish", "description": "Polish the UI"}]
        assert "frontend-polish" in local_skills_instructions()
        assert "desktop_skill_read" in local_skills_instructions()
        assert await run_computer_tool("desktop_skill_read", {"skill_id": "fixture", "path": "references/ui.md"}, 123) == "Local skill resource"
        await chunk("Skill applied")
    monkeypatch.setattr(desktop, "run_chat", fake_chat)
    monkeypatch.setattr(desktop, "run_local_chat", fake_chat)
    with TestClient(app).websocket_connect("/desktop/ws") as ws:
        ws.send_json({"type": "auth", "payload": {"token": token}})
        ws.receive_json()
        ws.send_json({"type": "run", "payload": {"mode": "director", "content": "polish", "skills": [{"id": "fixture", "name": "frontend-polish", "description": "Polish the UI"}]}})
        call = ws.receive_json()
        assert call["payload"]["name"] == "desktop_skill_read"
        assert call["payload"]["arguments"]["path"] == "references/ui.md"
        ws.send_json({"type": "tool_result", "payload": {"id": call["payload"]["id"], "ok": True, "output": "Local skill resource"}})
        assert ws.receive_json()["payload"]["text"] == "Skill applied"
        assert ws.receive_json()["type"] == "done"
    assert desktop_skills.get() == []


@pytest.mark.parametrize("tier,models", [("free", {"auto"}), ("pro", {"auto", "studio", "gpt-6-sol"}), ("proplus", {"auto", "studio", "gpt-6-sol"})])
def test_desktop_answer_modes_follow_site_plan(monkeypatch, account, tier, models):
    email, token = account
    async def subscription(user):
        return {"tier": tier}
    monkeypatch.setattr(desktop, "subscription_payload", subscription)
    response = TestClient(app).get("/desktop/status", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 200
    assert set(response.json()["chat_models"]) == models
