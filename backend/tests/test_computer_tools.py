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


def _letter() -> bytes:
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = "agent@ship.example", "ers@bitship.ru", "Docs for MV Aurora"
    msg.set_content("См. вложение")
    msg.add_attachment(b"%PDF-1.4 certificate", maintype="application", subtype="pdf", filename="Cert: A/B.pdf")
    msg.add_attachment(b"%PDF-1.4 again", maintype="application", subtype="pdf", filename="Cert: A/B.pdf")
    msg.add_attachment(b"\x89PNG", maintype="image", subtype="png", filename="logo.png", disposition="inline")
    return msg.as_bytes()


class _FakeMailbox:
    def select(self, folder, readonly=False):
        assert readonly

    def uid(self, command, uid, spec):
        assert command == "FETCH" and uid == "7"
        return "OK", [(b"7 (BODY[] {1}", _letter()), b")"]

    def logout(self):
        pass


def test_attachments_are_saved_to_the_sandbox_with_safe_unique_names(monkeypatch, tmp_path):
    import computer_tools
    import document_parser

    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path))
    monkeypatch.setattr(computer_tools, "_imap_connect", lambda payload: _FakeMailbox())

    async def fake_extract(data, name, **kwargs):
        return "Certificate of MV Aurora"

    monkeypatch.setattr(document_parser, "extract_text_from_file", fake_extract)
    result = asyncio.run(computer_tools._gmail_attachments({"email": "e"}, "7", "INBOX", 91001))
    assert "Subject: Docs for MV Aurora" in result and "Certificate of MV Aurora" in result
    assert "Почта/7/Cert_ A_B.pdf" in result and "Почта/7/Cert_ A_B_2.pdf" in result
    assert "logo.png (картинка в тексте письма)" in result
    from app.services.workspace_fs import user_root

    assert (user_root(91001) / "Почта" / "7" / "Cert_ A_B_2.pdf").read_bytes() == b"%PDF-1.4 again"


def test_imap_host_cannot_point_inside_the_server():
    from computer_tools import _imap_connect

    for host in ("localhost", "127.0.0.1", "10.0.0.5"):
        with pytest.raises(ValueError):
            _imap_connect({"email": "a@b.c", "app_password": "x", "imap_host": host})


def test_saved_imap_host_survives_a_resent_password():
    from app.services import connectors as store
    from app.services.chat_access import resolve

    uid = 91002
    for item in store.list_public(uid):
        store.delete_connector(uid, item["id"])
    args = {"email": "ers@bitship.ru", "app_password": "pass-12345"}
    resolve(uid, "gmail", {**args, "imap_host": "mail.nic.ru"})
    payload, _ = resolve(uid, "gmail", args)
    assert payload["imap_host"] == "mail.nic.ru" and payload["imap_port"] == 993


class _ListMailbox:
    """200 letters, UIDs 1..200; every 10th has an attachment."""

    def select(self, folder, readonly=False):
        assert readonly

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [" ".join(map(str, range(1, 201))).encode()]
        wanted = [int(u) for u in args[0].split(",")]
        out = []
        for uid in wanted:
            ctype = "multipart/mixed" if uid % 10 == 0 else "text/plain"
            raw = f"From: a{uid}@x.ru\r\nSubject: Letter {uid}\r\nContent-Type: {ctype}\r\n\r\n".encode()
            out += [(f"{uid} (UID {uid} BODY[HEADER.FIELDS (FROM)] {{{len(raw)}}}".encode(), raw), b")"]
        return "OK", out

    def logout(self):
        pass


def test_gmail_list_pages_through_the_whole_mailbox(monkeypatch):
    import re

    import computer_tools

    monkeypatch.setattr(computer_tools, "_imap_connect", lambda payload: _ListMailbox())
    seen, cursor = [], 0
    for _ in range(10):
        page = computer_tools._gmail_list_sync({}, "INBOX", 50, "ALL", cursor)
        seen += [int(u) for u in re.findall(r"^UID (\d+)", page, re.M)]
        found = re.search(r"before_uid=(\d+)", page)
        if not found:
            assert "последняя страница" in page
            break
        cursor = int(found.group(1))
    assert seen == list(range(200, 0, -1))  # nothing skipped, nothing repeated
    assert "UID 200 (возможны вложения)" in page or "UID 200 (возможны вложения)" in computer_tools._gmail_list_sync({}, "INBOX", 5, "ALL")
    assert "UID 199\n" in computer_tools._gmail_list_sync({}, "INBOX", 5, "ALL")
    assert computer_tools._gmail_list_sync({}, "INBOX", 5, "ALL", 1).startswith("Это конец")
