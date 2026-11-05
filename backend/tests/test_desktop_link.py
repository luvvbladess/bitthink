import threading
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import desktop_link
from app.auth import create_access_token_for_user
from app.core.repository import repo
from app.db.engine import SyncSessionLocal
from app.db.models import User
from app.main import app
from app.services.desktop_link import link_hub, normalize_state


@pytest.fixture(autouse=True)
def clean_link():
    link_hub.reset()
    yield
    link_hub.reset()


@pytest.fixture
def account():
    email = f"link-{uuid4().hex}@example.com"
    with SyncSessionLocal() as db:
        db.add(User(email=email, password_hash="test-only", role="user", bot_user_id=repo._bot_id(email)))
        db.commit()
    return email, create_access_token_for_user(email, "user")


def headers(token):
    return {"Authorization": "Bearer " + token}


def snapshot(session_id="session-001", status="idle", approval=None):
    return {
        "device_name": "WORKSTATION",
        "client_version": "0.9.6",
        "approval_mode": "ask",
        "projects": [{"id": "project-001", "name": "Чертежи"}],
        "sessions": [{
            "id": session_id,
            "title": "Собрать отчёт",
            "project_id": "project-001",
            "project_name": "Чертежи",
            "status": status,
            "updated_at": 1_700_000_000_000,
            "pending_approval": approval,
            "messages": [
                {"id": "message-001", "role": "user", "content": "Собери отчёт"},
                {"id": "message-002", "role": "assistant", "content": "Смотрю файлы", "tools": [{"name": "workspace_read", "status": "done"}]},
            ],
        }],
    }


def test_link_requires_login():
    assert TestClient(app).get("/desktop/link").status_code == 401


def test_state_is_clipped_and_drops_foreign_fields():
    state = normalize_state({
        "device_name": "A" * 80,
        "approval_mode": "nope",
        "projects": [{"id": "project-001", "name": "Папка", "cwd": "C:\\secret"}],
        "sessions": [{
            "id": "session-001",
            "title": "Чат",
            "project_id": "missing-01",
            "status": "needs_approval",
            "messages": [{"id": "message-001", "role": "user", "content": "x" * 4000, "secret": "no"}],
        }],
    })
    assert len(state["device_name"]) == 64
    assert state["approval_mode"] == "ask"
    assert "cwd" not in state["projects"][0]
    assert state["sessions"][0]["project_id"] == ""
    assert state["sessions"][0]["status"] == "running"
    assert len(state["sessions"][0]["messages"][0]["content"]) == 2500
    assert "secret" not in state["sessions"][0]["messages"][0]


def test_website_sees_only_its_open_client(account):
    email, token = account
    other = f"other-{uuid4().hex}@example.com"
    with SyncSessionLocal() as db:
        db.add(User(email=other, password_hash="test-only", role="user", bot_user_id=repo._bot_id(other)))
        db.commit()
    other_token = create_access_token_for_user(other, "user")
    client = TestClient(app)
    with client.websocket_connect("/desktop/link/ws") as ws:
        client.portal = ws.portal
        ws.send_json({"type": "auth", "payload": {"token": token}})
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "state", "payload": snapshot()})
        found = {}
        for _ in range(30):
            found = client.get("/desktop/link", headers=headers(token)).json()
            if found.get("online") and found.get("sessions"):
                break
            time.sleep(0.02)
        assert found["online"] is True
        assert found["device_name"] == "WORKSTATION"
        assert found["sessions"][0]["title"] == "Собрать отчёт"
        assert "messages" not in found["sessions"][0]
        detail = client.get("/desktop/link/sessions/session-001", headers=headers(token)).json()
        assert detail["messages"][1]["content"] == "Смотрю файлы"
        assert client.get("/desktop/link", headers=headers(other_token)).json()["online"] is False
        assert client.post("/desktop/link/sessions/session-001/stop", headers=headers(token)).status_code == 409
    client.portal = None
    offline = client.get("/desktop/link", headers=headers(token)).json()
    assert offline["online"] is False
    assert offline["sessions"][0]["status"] == "offline"


def test_website_prompt_stop_and_approval_reach_the_open_client(account):
    _, token = account
    seen = []
    client = TestClient(app)

    def pump(ws):
        for _ in range(3):
            frame = ws.receive_json()
            seen.append(frame)
            ws.send_json({"type": "ack", "payload": {"id": frame["payload"]["id"], "ok": True, "message": "Принято"}})

    with client.websocket_connect("/desktop/link/ws") as ws:
        client.portal = ws.portal
        ws.send_json({"type": "auth", "payload": {"token": token}})
        assert ws.receive_json()["type"] == "ready"
        approval = {"tool_id": "tool-000111", "name": "desktop_run_command", "summary": "Get-ChildItem"}
        ws.send_json({"type": "state", "payload": snapshot(status="needs_approval", approval=approval)})
        auth = headers(token)
        for _ in range(50):
            view = client.get("/desktop/link", headers=auth).json()
            if view.get("sessions") and view["sessions"][0]["status"] == "needs_approval":
                break
            time.sleep(0.02)
        listener = threading.Thread(target=pump, args=(ws,))
        listener.start()
        denied = client.post("/desktop/link/sessions/session-001/approval", headers=auth, json={"tool_id": "tool-999999", "allow": True})
        assert denied.status_code == 409
        allowed = client.post("/desktop/link/sessions/session-001/approval", headers=auth, json={"tool_id": "tool-000111", "allow": False})
        assert allowed.status_code == 200
        created = client.post("/desktop/link/sessions", headers=auth, json={"project_id": "project-001", "content": "Проверь чертёж"})
        assert created.status_code == 200
        assert len(created.json()["session_id"]) == 32
        sent = client.post("/desktop/link/sessions/session-001/message", headers=auth, json={"content": "Продолжи с готового файла"})
        assert sent.status_code == 200
        assert sent.json()["message"] == "Принято"
        listener.join(5)
        assert not listener.is_alive()
    client.portal = None
    actions = [frame["payload"]["action"] for frame in seen]
    assert actions == ["approve", "create", "prompt"]
    assert seen[1]["payload"]["content"] == "Проверь чертёж"
    assert seen[2]["payload"]["content"] == "Продолжи с готового файла"
    assert client.get("/desktop/link", headers=headers(token)).json()["online"] is False


def test_second_client_replaces_the_first(account):
    _, token = account
    client = TestClient(app)
    first = client.websocket_connect("/desktop/link/ws").__enter__()
    client.portal = first.portal
    first.send_json({"type": "auth", "payload": {"token": token}})
    assert first.receive_json()["type"] == "ready"
    first.send_json({"type": "state", "payload": snapshot()})
    second = client.websocket_connect("/desktop/link/ws").__enter__()
    second.send_json({"type": "auth", "payload": {"token": token}})
    assert second.receive_json()["type"] == "ready"
    replaced = first.receive_json()
    assert replaced["type"] == "replaced"
    second.send_json({"type": "state", "payload": snapshot()})
    second.send_json({"type": "state", "payload": {**snapshot(), "device_name": "LAPTOP"}})
    found = {}
    for _ in range(30):
        found = client.get("/desktop/link", headers=headers(token)).json()
        if found.get("device_name") == "LAPTOP":
            break
        time.sleep(0.02)
    assert found["device_name"] == "LAPTOP"
    second.close()
    first.close()
    second.__exit__(None, None, None)
    first.__exit__(None, None, None)


def test_prompt_without_a_client_is_refused(account):
    _, token = account
    response = TestClient(app).post("/desktop/link/sessions/session-001/message", headers=headers(token), json={"content": "Привет"})
    assert response.status_code == 409
    assert "Bit Client" in response.json()["detail"]
    assert desktop_link.OFFLINE in response.json()["detail"]


@pytest.mark.parametrize('field', ['projects', 'sessions'])
@pytest.mark.parametrize('value', [42, True, 'bad', {'id': 'not-a-list'}])
def test_malformed_snapshot_lists_are_empty(field,value):
    assert normalize_state({field:value})[field]==[]
