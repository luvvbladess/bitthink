from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.core.repository import repo
from app.db.engine import SyncSessionLocal
from app.db.models import User
from app.main import app


def test_empty_conversations_are_distinct_even_when_created_concurrently(monkeypatch):
    email = f"new-chats-{uuid4().hex}@example.com"
    with SyncSessionLocal() as session:
        session.add(User(email=email, password_hash="test", role="user", bot_user_id=repo._bot_id(email)))
        session.commit()
    monkeypatch.setitem(app.dependency_overrides, get_current_user, lambda: email)
    client = TestClient(app)

    def create(_index):
        response = client.post('/conversations', json={'title': 'Новый чат'})
        assert response.status_code == 200, response.text
        return response.json()['id']

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(create, range(4)))
    assert len(set(ids)) == 4
    listed = client.get('/conversations').json()
    # Opening the list drops the unused drafts. The open one stays, so a blank composer is not lost.
    assert len(listed) == 1 and listed[0]['id'] in ids and listed[0]['is_active']
    kept = listed[0]['id']
    assert client.get(f'/conversations/{kept}/messages').json() == []
    for conversation_id in ids:
        if conversation_id == kept:
            continue
        assert client.get(f'/conversations/{conversation_id}/summary').status_code == 404
