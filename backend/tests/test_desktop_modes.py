import base64
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.api import desktop
from app.auth import create_access_token_for_user
from app.core.repository import repo
from app.core.request_context import generation_preferences
from app.db.engine import SyncSessionLocal
from app.db.models import User
from app.services.desktop_context import desktop_chat_model, desktop_executor, desktop_cwd
from app.services.chat_modes import normalize_chat_mode, PUBLIC_CHAT_MODE_IDS


@pytest.fixture
def token():
    email=f'desktop-modes-{uuid4().hex}@example.invalid'
    with SyncSessionLocal() as db:
        db.add(User(email=email,password_hash='synthetic',role='user',bot_user_id=repo._bot_id(email)));db.commit()
    return email,create_access_token_for_user(email,'user')


@pytest.mark.parametrize('value,expected',[
    ('studio','auto'),('gpt-6-luna','auto'),('gpt-6.1-terra','auto'),
    ('claude-opus-5.5','auto'),('deepseek-v4-pro','auto'),('kimi-k2.6','search'),
    ('gpt-6-sol','gpt-6-sol'),('gpt-6-astra','gpt-6-astra'),('docgen','docgen'),('director','director'),
])
def test_desktop_wire_choices_are_product_modes(value,expected):
    assert normalize_chat_mode(value)==expected
    assert expected in PUBLIC_CHAT_MODE_IDS


@pytest.mark.parametrize('requested,expected',[('claude-opus-5.5','auto'),('studio','auto'),('kimi-k2.6','search'),('gpt-6-sol','gpt-6-sol')])
def test_desktop_request_binds_mode_and_exact_canvas_without_persisting_account_choice(monkeypatch,token,requested,expected):
    email,access=token
    save=AsyncMock(side_effect=AssertionError('Per-chat mode must not change the account setting'))
    monkeypatch.setattr(repo,'set_user_model',save)
    async def chat(user,content,cid,status,chunk,file,**kwargs):
        assert user==email and content=='Change this canvas'
        assert desktop_chat_model.get()==expected
        assert desktop_executor.get() is None and desktop_cwd.get()==''
        preferences=generation_preferences.get()
        assert preferences['user_id']==repo._bot_id(email)
        assert preferences['selected_model']==expected and preferences['canvas_target']=='/uploads/generated/old.html'
        await chunk('bound')
    monkeypatch.setattr(desktop,'run_chat',chat)
    with TestClient(app).websocket_connect('/desktop/ws') as ws:
        ws.send_json({'type':'auth','payload':{'token':access}});ws.receive_json()
        ws.send_json({'type':'run','payload':{'mode':'chat','chat_model':requested,'canvas_target':'/uploads/generated/old.html','cwd':'C:/private','content':'Change this canvas'}})
        frames=[]
        while True:
            frame=ws.receive_json();frames.append(frame)
            if frame['type']=='done':break
        assert any(frame['type']=='text' and frame['payload']['text']=='bound' for frame in frames)
        assert not any(frame['type']=='error' for frame in frames)
    save.assert_not_awaited()
    assert generation_preferences.get() is None


def test_url_backed_web_result_arrives_as_real_file_bytes_for_desktop(monkeypatch,token,tmp_path):
    _,access=token
    path=tmp_path/'canvas.html';path.write_bytes(b'<!doctype html><html><body>real output</body></html>')
    monkeypatch.setattr(repo._manager,'_attachment_disk_path',lambda attachment:path)
    async def chat(user,content,cid,status,chunk,file,**kwargs):
        await file('canvas.html',b'','/uploads/generated/canvas.html')
    monkeypatch.setattr(desktop,'run_chat',chat)
    with TestClient(app).websocket_connect('/desktop/ws') as ws:
        ws.send_json({'type':'auth','payload':{'token':access}});ws.receive_json()
        ws.send_json({'type':'run','payload':{'mode':'chat','content':'Create a canvas'}})
        files=[]
        while True:
            frame=ws.receive_json()
            if frame['type']=='file':files.append(frame['payload'])
            if frame['type']=='done':break
        assert len(files)==1 and base64.b64decode(files[0]['data'])==path.read_bytes()
        assert files[0]['url']=='/uploads/generated/canvas.html'
