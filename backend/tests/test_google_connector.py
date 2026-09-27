import asyncio
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import decode_token
from app.config import get_settings
from app.main import app
from app.services import connectors as store
from app.services import google_oauth
import computer_tools  # noqa: F401 — bot_core on sys.path via app.config
import google_tools


def _state_from(url: str) -> str:
    return parse_qs(urlparse(url).query)["state"][0]


def test_state_needs_the_cookie_of_the_browser_that_started(monkeypatch):
    monkeypatch.setattr(get_settings(), "GOOGLE_CLIENT_ID", "cid")
    url, nonce = google_oauth.start(4242, "https://bit-think.space")
    state = _state_from(url)
    assert parse_qs(urlparse(url).query)["redirect_uri"] == ["https://bit-think.space/api/connectors/google/callback"]
    assert google_oauth.read_state(state, nonce)["uid"] == 4242
    for cookie in (None, "", "someone-else"):
        with pytest.raises(google_oauth.GoogleAuthError):
            google_oauth.read_state(state, cookie)
    # The state is signed with the login secret but must never pass as a login token.
    with pytest.raises(HTTPException):
        decode_token(state)


def test_callback_with_forged_state_changes_nothing():
    response = TestClient(app).get(
        "/connectors/google/callback", params={"state": "forged", "code": "x"}, follow_redirects=False
    )
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/settings?google=expired"


def test_pilot_points_to_settings_without_google():
    result = asyncio.run(computer_tools.run_computer_tool("google_mail_search", {}, user_id=93101))
    assert "Настройки" in result


def test_mail_search_through_pilot(monkeypatch):
    uid = 93102
    for item in store.list_public(uid):
        store.delete_connector(uid, item["id"])
    store.upsert_connector(uid, "google", "me@gmail.com", {"email": "me@gmail.com", "refresh_token": "1//secret-refresh"})
    calls = []

    async def fake_api(payload, method, url, **kwargs):
        calls.append((url, kwargs.get("params")))
        assert payload["refresh_token"] == "1//secret-refresh"
        if url.endswith("/messages"):
            return {"messages": [{"id": "abc123"}]}
        return {
            "id": "abc123",
            "labelIds": ["UNREAD"],
            "snippet": "Счёт во вложении",
            "payload": {"headers": [{"name": "From", "value": "ivan@example.com"}, {"name": "Subject", "value": "Счёт"}]},
        }

    monkeypatch.setattr(google_tools, "api", fake_api)
    result = asyncio.run(
        computer_tools.run_computer_tool("google_mail_search", {"query": "is:unread"}, user_id=uid)
    )
    assert "id abc123 (не прочитано)" in result and "ivan@example.com" in result
    assert calls[0][1]["q"] == "is:unread"
    assert "1//secret-refresh" in store.secret_values(uid)  # redacted if it ever leaks into chat


def test_mail_body_and_drive_query():
    part = {
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "text/html", "body": {"data": "PGI-aGk8L2I-"}},
            {"mimeType": "text/plain", "body": {"data": "0L_RgNC40LLQtdGC"}},
            {"mimeType": "application/pdf", "filename": "act.pdf", "body": {"attachmentId": "a"}},
        ],
    }
    plain, html, files = google_tools._mail_body(part)
    assert plain == "привет" and html == "<b>hi</b>" and files == ["act.pdf"]
    assert google_tools._drive_query("it's") == "(name contains 'it\\'s' or fullText contains 'it\\'s') and trashed = false"


def test_send_and_upload_need_the_new_permissions_and_work_with_them(monkeypatch, tmp_path):
    import base64
    import email
    import email.policy

    uid = 93103
    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path))
    from app.services.workspace_fs import user_root

    (user_root(uid) / "komplekt").mkdir(parents=True)
    (user_root(uid) / "komplekt" / "01_Отчёт.docx").write_bytes(b"PK\x03\x04docx")
    for item in store.list_public(uid):
        store.delete_connector(uid, item["id"])
    old = {"email": "me@gmail.com", "refresh_token": "1//r", "scopes": ["https://www.googleapis.com/auth/gmail.readonly"]}
    store.upsert_connector(uid, "google", "me@gmail.com", old)
    calls = []

    async def fake_api(payload, method, url, **kwargs):
        calls.append((method, url, kwargs))
        if "upload" in url:
            return {"id": "f1", "name": "01_Отчёт.docx", "webViewLink": "https://drive.google.com/file/d/f1"}
        return {"id": "m1"}

    monkeypatch.setattr(google_tools, "api", fake_api)
    send = {"to": "ivan@example.com", "subject": "Отчёт", "body": "Добрый день, отчёт во вложении.",
            "attachments": ["komplekt/01_Отчёт.docx"]}
    run = lambda name, args: asyncio.run(computer_tools.run_computer_tool(name, args, user_id=uid))  # noqa: E731

    # Connected before these permissions existed: ask to reconnect, send nothing.
    assert "Подключить заново" in run("google_mail_send", send)
    assert "Подключить заново" in run("google_drive_upload", {"file": "komplekt/01_Отчёт.docx"})
    assert calls == []

    store.upsert_connector(uid, "google", "me@gmail.com", {**old, "scopes": list(google_oauth.SCOPES)})
    assert "Письмо отправлено: ivan@example.com" in run("google_mail_send", send)
    method, url, kwargs = calls[-1]
    assert method == "POST" and url.endswith("/messages/send")
    sent = email.message_from_bytes(base64.urlsafe_b64decode(kwargs["json_body"]["raw"]), policy=email.policy.default)
    assert sent["To"] == "ivan@example.com" and [p.get_filename() for p in sent.iter_attachments()] == ["01_Отчёт.docx"]

    assert "https://drive.google.com/file/d/f1" in run("google_drive_upload", {"file": "komplekt/01_Отчёт.docx"})
    method, url, kwargs = calls[-1]
    assert kwargs["params"]["uploadType"] == "multipart" and b"PK\x03\x04docx" in kwargs["data"]

    # Bad addresses and escaping the sandbox are refused before any call.
    before = len(calls)
    assert "адреса" in run("google_mail_send", {**send, "to": "not-an-email"})
    assert "не найден" in run("google_drive_upload", {"file": "../../etc/passwd"})
    assert len(calls) == before
    for item in store.list_public(uid):
        store.delete_connector(uid, item["id"])


def test_drive_trash_by_default_and_permanent_only_when_asked(monkeypatch):
    uid = 93104
    for item in store.list_public(uid):
        store.delete_connector(uid, item["id"])
    full = {"email": "me@gmail.com", "refresh_token": "1//r", "scopes": list(google_oauth.SCOPES)}
    store.upsert_connector(uid, "google", "me@gmail.com", full)
    calls = []

    async def fake_api(payload, method, url, **kwargs):
        calls.append(method)
        if "gone" in url and method != "GET":
            raise google_oauth.GoogleAuthError("Google API 404: notFound")
        return {"id": "f1", "name": "Рассказ.docx"}

    monkeypatch.setattr(google_tools, "api", fake_api)
    run = lambda args: asyncio.run(computer_tools.run_computer_tool("google_drive_trash", args, user_id=uid))  # noqa: E731

    assert "в корзину" in run({"file_id": "f1"}) and calls[-1] == "PATCH"
    assert "навсегда" in run({"file_id": "f1", "permanent": True}) and calls[-1] == "DELETE"
    assert "нет прав" in run({"file_id": "gone"})
    # Connected with the older drive.file permission: someone else's file needs a reconnect.
    old = {**full, "scopes": ["https://www.googleapis.com/auth/drive.file"]}
    store.upsert_connector(uid, "google", "me@gmail.com", old)
    assert "Подключить заново" in run({"file_id": "gone"})
    for item in store.list_public(uid):
        store.delete_connector(uid, item["id"])


def test_drive_search_can_look_into_the_trash(monkeypatch):
    seen = []

    async def fake_api(payload, method, url, **kwargs):
        seen.append(kwargs["params"]["q"])
        return {"files": []}

    monkeypatch.setattr(google_tools, "api", fake_api)
    assert asyncio.run(google_tools._drive_search({}, {"query": "впадина", "in_trash": True})) == "В корзине Диска таких файлов нет."
    assert asyncio.run(google_tools._drive_search({}, {"query": "впадина"})) == "Файлов не найдено."
    assert seen[0].endswith("trashed = true") and seen[1].endswith("trashed = false")
