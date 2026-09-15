import asyncio

import pytest

from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path
from computer_tools import _SAFE_IMAP_SEARCH, _assert_public_http_url, run_computer_tool


def test_localhost_browse_is_blocked():
    with pytest.raises(ValueError):
        _assert_public_http_url("http://127.0.0.1/secret")
    with pytest.raises(ValueError):
        _assert_public_http_url("http://localhost/admin")


def test_imap_search_is_allowlisted():
    assert _SAFE_IMAP_SEARCH.match("UNSEEN")
    assert _SAFE_IMAP_SEARCH.match('FROM "a@b.c"')
    assert not _SAFE_IMAP_SEARCH.match("ALL) (UID 1")


def test_gmail_tool_requires_chat_credentials():
    result = asyncio.run(run_computer_tool("gmail_list", {"connector_id": 999999}, user_id=1))
    assert "не найден" in result.lower() or "доступ" in result.lower()
