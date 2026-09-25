"""Proofs for the second audit pass: isolation, attachments, quota, delivery."""

import asyncio
import os
import subprocess
import sys
import threading
from pathlib import Path

from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path
from app.billing.plans import plan_for
from app.billing.quota import QuotaError, apply_token_debit, assert_can_use
from app.bot_core.db_conversations import DatabaseConversationManager
from app.core.repository import ConversationRepository
from app.db.engine import SyncSessionLocal
from app.db.models import Subscription, User


def _ensure_user(email: str, bot_id: int) -> None:
    with SyncSessionLocal() as session:
        row = session.query(User).filter_by(email=email).one_or_none()
        if row is None:
            session.add(User(email=email, password_hash="x", role="user", bot_user_id=bot_id))
            session.commit()


def _cleanup(manager: DatabaseConversationManager, *conv_ids: str) -> None:
    for conv_id in conv_ids:
        owner = manager.conversation_owner(conv_id)
        if owner:
            manager.delete_conversation(owner, conv_id)


def test_sandbox_token_fails_closed_and_matches():
    root = Path(__file__).resolve().parents[2]
    code = (
        "import os, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import server\n"
        "os.environ['SANDBOX_TOKEN'] = 's3cret'\n"
        "assert server.sandbox_token_ok('s3cret')\n"
        "assert not server.sandbox_token_ok('other')\n"
        "assert not server.sandbox_token_ok('')\n"
        "os.environ['SANDBOX_TOKEN'] = ''\n"
        "assert not server.sandbox_token_ok('s3cret')\n"
        "print('ok')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code, str(root / "backend" / "app" / "services")],
        cwd=str(root / "sandbox"),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


def test_sitecustomize_blocks_loopback():
    root = Path(__file__).resolve().parents[2]
    code = (
        "import sitecustomize\n"
        "assert sitecustomize._blocked_host('127.0.0.1')\n"
        "assert sitecustomize._blocked_host('::1')\n"
        "assert sitecustomize._blocked_host('localhost')\n"
        "assert sitecustomize._blocked_host('0.0.0.0')\n"
        "assert not sitecustomize._blocked_host('1.1.1.1')\n"
        "print('ok')\n"
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root / "sandbox")
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


def test_guest_cannot_remove_owners_attachment():
    manager = DatabaseConversationManager()
    repo = ConversationRepository()
    owner_email = "round2-owner@example.com"
    guest_email = "round2-guest@example.com"
    owner = repo._bot_id(owner_email)
    guest = repo._bot_id(guest_email)
    _ensure_user(owner_email, owner)
    _ensure_user(guest_email, guest)
    owned = manager.create_conversation(owner, title="Вложения")
    token = manager.create_share(owner, owned.id)
    assert manager.join_share(guest, token)["id"] == owned.id
    try:
        posted = manager.add_message(
            owner,
            "user",
            "brief.docx",
            conv_id=owned.id,
            attachment={"name": "brief.docx", "type": "document"},
            author_user_id=owner,
        )
        assert manager.remove_attachment(guest, "brief.docx", owned.id, posted.db_id) is None
        assert manager.conversation_view(owner, owned.id).messages[-1].content == "brief.docx"
        assert manager.remove_attachment(guest, "brief.docx", owned.id) is None
        removed = manager.remove_attachment(owner, "brief.docx", owned.id, posted.db_id)
        assert removed and removed["name"] == "brief.docx"
        assert manager.conversation_view(owner, owned.id).messages == []
    finally:
        _cleanup(manager, owned.id)


def test_supersede_drops_old_interim_and_keeps_the_new_one():
    manager = DatabaseConversationManager()
    owner = 976_200_001
    conv = manager.create_conversation(owner, title="Пилот")
    try:
        manager.add_message(owner, "user", "сделай комплект", conv_id=conv.id, author_user_id=owner)
        interim = manager.add_message(
            owner,
            "assistant",
            "черновик",
            conv_id=conv.id,
            attachment={"name": "draft.docx", "interim": True},
        )
        final = manager.add_message(owner, "assistant", "готово", conv_id=conv.id)
        newer = manager.add_message(
            owner,
            "assistant",
            "новый черновик",
            conv_id=conv.id,
            attachment={"name": "next.docx", "interim": True},
        )
        manager.add_message(
            owner,
            "assistant",
            "новый ответ",
            conv_id=conv.id,
            supersede_message_id=final.db_id,
        )
        contents = [item.content for item in manager.conversation_view(owner, conv.id).messages]
        assert "черновик" not in contents
        assert "готово" not in contents
        assert contents == ["сделай комплект", "новый черновик", "новый ответ"]
        assert interim.db_id and newer.db_id
        assert manager.delete_interim_after(owner, conv.id, final.db_id) == 1
        left = [item.content for item in manager.conversation_view(owner, conv.id).messages]
        assert left == ["сделай комплект", "новый ответ"]
    finally:
        _cleanup(manager, conv.id)


def test_image_quota_is_atomic():
    manager = DatabaseConversationManager()
    uid = 976_200_002
    manager.set_subscription_tier(uid, "pro", 30)
    limit = int(plan_for("pro")["images"])
    with SyncSessionLocal() as session:
        sub = session.query(Subscription).filter_by(user_id=uid).one()
        sub.images_used = limit - 1
        session.commit()
    results: list[bool] = []

    def once():
        results.append(manager.try_consume_images(uid, 1))

    threads = [threading.Thread(target=once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(True) == 1
    assert manager.get_subscription(uid)["images_used"] == limit
    manager.refund_plan_images(uid, 1)
    assert manager.get_subscription(uid)["images_used"] == limit - 1


def test_paid_window_hold_is_atomic_and_capped():
    manager = DatabaseConversationManager()
    uid = 976_200_003
    manager.set_subscription_tier(uid, "pro", 30)
    session_limit = int(plan_for("pro")["chat_session"])
    manager.debit_plan_tokens(uid, "chat", session_limit - 1)
    won: list[str] = []
    lost: list[str] = []

    def once():
        try:
            assert_can_use(uid, "chat", "gpt-6-luna")
            won.append("ok")
        except QuotaError as exc:
            lost.append(str(exc))

    threads = [threading.Thread(target=once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(won) == 1
    assert len(lost) == 1
    assert "Пятичасовое" in lost[0]
    stored = manager.get_subscription(uid)
    assert stored["session_chat_used"] == session_limit
    manager.release_paid_window(uid, "chat")
    assert manager.get_subscription(uid)["session_chat_used"] == session_limit - 1

    sample = {
        "tier": "pro",
        "expires_at": 0,
        "session_started_at": 10**10,
        "session_chat_used": session_limit - 10,
        "chat_tokens_used": 0,
        "week_chat_used": 0,
        "period_start": "2099-01",
        "week_start": "2099-01-05",
        "last_reset_date": "2099-01-06",
    }
    apply_token_debit(sample, "chat", 100)
    assert sample["session_chat_used"] == session_limit
    assert sample["chat_tokens_used"] == 100


def test_empty_model_reply_is_not_charged(monkeypatch):
    import config as bot_config

    bot_config.OPENAI_API_KEY = "sk-audit-test"
    from app.bot_core import openai_client

    tracked = {}

    def track(*_args, **_kwargs):
        tracked["yes"] = True

    refunded = {}

    def refund():
        refunded["yes"] = True

    monkeypatch.setattr(openai_client.conversation_manager, "track_tokens", track)
    monkeypatch.setattr("app.billing.quota.refund_quota_charge", refund)
    asyncio.run(openai_client._settle_model_usage(7, "gpt-6-luna", 3, 0, 0, 0, "   ", []))
    assert "yes" not in tracked
    assert refunded.get("yes")
    asyncio.run(openai_client._settle_model_usage(7, "gpt-6-luna", 3, 1, 0, 0, "", [{"bytes": b"x"}]))
    assert tracked.get("yes")


def test_astra_fallback_forwards_tool_budget():
    source = Path("app/bot_core/openai_client.py").read_text(encoding="utf-8")
    assert "use_skills=use_skills" in source
    assert "chat_tools=chat_tools" in source
    assert "max_tool_loops=max_tool_loops" in source


def test_load_source_bytes_checks_owner():
    from fastapi import HTTPException

    from app.api.media import _load_source_bytes

    other = "b" * 16
    url = f"/uploads/generated/{other}/{'c' * 32}.png"
    try:
        asyncio.run(_load_source_bytes("alice@example.com", url))
    except HTTPException as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("foreign upload must be rejected")


def test_image_job_takes_the_chat_slot():
    from app.services.generation_hub import GenerationHub

    hub = GenerationHub()
    hub.mark_busy("user-r2", "conv-r2")
    assert hub.is_running("user-r2", "conv-r2")
    assert hub.running_count("user-r2") == 1
    try:
        hub.mark_busy("user-r2", "conv-r2")
        raise AssertionError("second image must not take the slot")
    except RuntimeError:
        pass
    hub.clear_busy("user-r2", "conv-r2")
    assert not hub.is_running("user-r2", "conv-r2")


def test_truncate_is_blocked_while_a_reply_runs():
    os.environ["SECRET_KEY"] = "audit-test-secret-key-not-default"
    os.environ["DEBUG"] = "true"
    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app.auth import create_access_token
    from app.main import app
    from app.services.generation_hub import hub

    manager = DatabaseConversationManager()
    repo = ConversationRepository()
    email = "round2-edit@example.com"
    bot_id = repo._bot_id(email)
    _ensure_user(email, bot_id)
    conv = manager.create_conversation(bot_id, title="Правка")
    manager.add_message(bot_id, "user", "первый", conv_id=conv.id, author_user_id=bot_id)
    hub.mark_busy(email, conv.id)
    client = TestClient(app)
    try:
        response = client.post(
            f"/conversations/{conv.id}/messages/truncate",
            json={"keep_count": 0},
            headers={"Authorization": f"Bearer {create_access_token({'sub': email})}"},
        )
        assert response.status_code == 409
        assert manager.conversation_view(bot_id, conv.id).messages[-1].content == "первый"
    finally:
        hub.clear_busy(email, conv.id)
        _cleanup(manager, conv.id)
