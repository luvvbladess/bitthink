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
