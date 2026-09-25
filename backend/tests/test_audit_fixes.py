"""Regression tests for the shared-chat, quota, auth, and generation-hub bugs."""

import asyncio
import threading
import time

from app.config import get_settings  # noqa: F401 — adds bot_core to sys.path
from app.billing.quota import QuotaError, assert_can_use, usage_view
from app.bot_core.db_conversations import DatabaseConversationManager
from app.bot_core.turn_scope import turn_conversation
from app.core.repository import ConversationRepository
from app.db.engine import SyncSessionLocal
from app.db.models import Conversation, Subscription, User


def _ensure_user(email: str, bot_id: int) -> None:
    with SyncSessionLocal() as session:
        row = session.query(User).filter_by(email=email).one_or_none()
        if row is None:
            session.add(User(email=email, password_hash="x", role="user", bot_user_id=bot_id))
            session.commit()


def _cleanup(*conv_ids: str) -> None:
    manager = DatabaseConversationManager()
    for conv_id in conv_ids:
        owner = manager.conversation_owner(conv_id)
        if owner:
            manager.delete_conversation(owner, conv_id)


def test_guest_without_personal_chat_can_send_in_shared_room():
    manager = DatabaseConversationManager()
    repo = ConversationRepository()
    owner_email = "audit-owner-5758@example.com"
    guest_email = "audit-guest-5758@example.com"
    owner = repo._bot_id(owner_email)
    guest = repo._bot_id(guest_email)
    _ensure_user(owner_email, owner)
    _ensure_user(guest_email, guest)
    owned = manager.create_conversation(owner, title="Общий")
    token = manager.create_share(owner, owned.id)
    assert manager.join_share(guest, token)["id"] == owned.id
    assert manager.get_active_conversation(guest) is None

    broadcasts = []

    async def fake_broadcast(user_id, message):
        broadcasts.append((user_id, message))

    from app.services.generation_hub import hub

    original = hub.broadcast
    hub.broadcast = fake_broadcast
    try:
        async def go():
            user_msg = await repo.add_message(guest_email, "user", "привет из общего", conv_id=owned.id)
            assistant = await repo.add_message(guest_email, "assistant", "ответ гостю", conv_id=owned.id)
            return user_msg, assistant

        user_msg, assistant = asyncio.run(go())
        assert user_msg["content"] == "привет из общего"
        assert assistant["id"].startswith(owned.id)
        room = manager.conversation_view(owner, owned.id)
        assert room is not None
        assert [item.content for item in room.messages] == ["привет из общего", "ответ гостю"]
        assert any(message["payload"]["conversation_id"] == owned.id for _, message in broadcasts)
    finally:
        hub.broadcast = original
        _cleanup(owned.id)


def test_tools_and_delete_stay_inside_the_open_room():
    manager = DatabaseConversationManager()
    repo = ConversationRepository()
    guest_email = "audit-docs-guest-5758@example.com"
    owner_email = "audit-docs-owner-5758@example.com"
    guest = repo._bot_id(guest_email)
    owner = repo._bot_id(owner_email)
    personal = manager.create_conversation(guest, title="Личный")
    shared = manager.create_conversation(owner, title="Общий")
    token = manager.create_share(owner, shared.id)
    manager.join_share(guest, token)
    manager.add_document(guest, "secret.txt", "personal-secret", conv_id=personal.id)
    manager.add_document(guest, "shared.txt", "shared-body", conv_id=shared.id)
    manager.add_document(guest, "same.txt", "personal-copy", conv_id=personal.id)
    manager.add_document(owner, "same.txt", "shared-copy", conv_id=shared.id)
    image = {"type": "image", "mime_type": "image/jpeg", "url": "/uploads/chat/x/p.jpg"}
    manager.add_message(
        guest, "user", "mine.jpg", conv_id=personal.id, author_user_id=guest,
        attachment={**image, "name": "mine.jpg"},
    )
    manager.add_message(
        owner, "user", "room.jpg", conv_id=shared.id, author_user_id=owner,
        attachment={**image, "name": "room.jpg", "url": "/uploads/chat/x/r.jpg"},
    )
    try:
        with turn_conversation(shared.id):
            names = {item["filename"] for item in manager.get_documents(guest)}
            assert names == {"shared.txt", "same.txt"}
            photos = [item["name"] for item in manager.list_chat_image_files(guest)]
            assert photos == ["room.jpg"]
            assert manager.remove_document(guest, "same.txt") is True
        personal_names = {item["filename"] for item in manager.get_documents(guest, conv_id=personal.id)}
        assert personal_names == {"secret.txt", "same.txt"}
        shared_names = {item["filename"] for item in manager.get_documents(guest, conv_id=shared.id)}
        assert "same.txt" not in shared_names
        assert "shared.txt" in shared_names
    finally:
        _cleanup(personal.id, shared.id)


def test_failed_generation_does_not_delete_someone_elses_message(monkeypatch):
    manager = DatabaseConversationManager()
    repo = ConversationRepository()
    owner_email = "audit-rollback-owner-5758@example.com"
    guest_email = "audit-rollback-guest-5758@example.com"
    owner = repo._bot_id(owner_email)
    guest = repo._bot_id(guest_email)
    shared = manager.create_conversation(owner, title="Общий")
    token = manager.create_share(owner, shared.id)
    manager.join_share(guest, token)
    manager.add_message(guest, "user", "вопрос гостя", conv_id=shared.id, author_user_id=guest)
    manager.add_message(owner, "user", "реплика владельца", conv_id=shared.id, author_user_id=owner)

    async def fail(*_args, **_kwargs):
        raise QuotaError("квота", "quota")

    monkeypatch.setattr("app.services.chat_service._generate_and_send", fail)

    async def silent(*_args, **_kwargs):
        return None

    from app.services.chat_service import run_chat

    try:
        try:
            asyncio.run(run_chat(guest_email, "новая реплика гостя", shared.id, silent, silent, silent))
            raise AssertionError("generation should fail")
        except QuotaError:
            pass
        contents = [item.content for item in manager.conversation_view(owner, shared.id).messages]
        assert contents == ["вопрос гостя", "реплика владельца"]
        # Owner's newer line stays; only the guest's own earlier line is removed.
        assert manager.delete_last_message(guest, shared.id, "user") is True
        contents = [item.content for item in manager.conversation_view(owner, shared.id).messages]
        assert contents == ["реплика владельца"]
    finally:
        _cleanup(shared.id)


def test_regenerate_keeps_previous_answer_until_success(monkeypatch):
    manager = DatabaseConversationManager()
    repo = ConversationRepository()
    owner_email = "audit-regen-owner-5758@example.com"
    guest_email = "audit-regen-guest-5758@example.com"
    owner = repo._bot_id(owner_email)
    guest = repo._bot_id(guest_email)
    shared = manager.create_conversation(owner, title="Общий")
    token = manager.create_share(owner, shared.id)
    manager.join_share(guest, token)
    manager.add_message(owner, "user", "вопрос владельца", conv_id=shared.id, author_user_id=owner)
    manager.add_message(owner, "assistant", "старый ответ", conv_id=shared.id)
    previous = manager.last_assistant_message_id(owner, shared.id)

    async def fail_quota(*_args, **_kwargs):
        raise QuotaError("квота", "quota")

    async def fail_cancel(*_args, **_kwargs):
        raise asyncio.CancelledError()

    async def silent(*_args, **_kwargs):
        return None

    from app.services.chat_service import regenerate_chat

    try:
        assert manager.can_regenerate(guest, shared.id) is False
        try:
            asyncio.run(regenerate_chat(guest_email, shared.id, silent, silent, silent))
            raise AssertionError("guest must not regenerate someone else's answer")
        except PermissionError:
            pass
        assert manager.conversation_view(owner, shared.id).messages[-1].content == "старый ответ"

        monkeypatch.setattr("app.services.chat_service._generate_and_send", fail_quota)
        try:
            asyncio.run(regenerate_chat(owner_email, shared.id, silent, silent, silent))
            raise AssertionError("quota failure should surface")
        except QuotaError:
            pass
        assert manager.conversation_view(owner, shared.id).messages[-1].content == "старый ответ"

        monkeypatch.setattr("app.services.chat_service._generate_and_send", fail_cancel)
        try:
            asyncio.run(regenerate_chat(owner_email, shared.id, silent, silent, silent))
            raise AssertionError("cancel should surface")
        except asyncio.CancelledError:
            pass
        assert manager.conversation_view(owner, shared.id).messages[-1].content == "старый ответ"

        manager.add_message(
            owner, "assistant", "новый ответ", conv_id=shared.id, supersede_message_id=previous,
        )
        contents = [item.content for item in manager.conversation_view(owner, shared.id).messages]
        assert contents == ["вопрос владельца", "новый ответ"]

        try:
            manager.truncate_after(guest, shared.id, 0)
            raise AssertionError("guest must not truncate the owner's turn")
        except PermissionError:
            pass
        assert manager.conversation_view(owner, shared.id).messages[-1].content == "новый ответ"
    finally:
        _cleanup(shared.id)


def test_expired_paid_tier_behaves_as_free():
    manager = DatabaseConversationManager()
    user_id = 975_800_005
    manager.set_subscription_tier(user_id, "pro", 30)
    with SyncSessionLocal() as session:
        sub = session.query(Subscription).filter_by(user_id=user_id).one()
        sub.expires_at = int(time.time()) - 3600
        sub.chat_tokens_used = 40
        session.commit()
    stored = manager.get_subscription(user_id)
    view = usage_view(stored)
    assert stored["tier"] == "free"
    assert stored["tier_raw"] == "pro"
    assert view["tier"] == "free"
    assert view["tier_raw"] == "pro"
    with SyncSessionLocal() as session:
        assert session.query(Subscription).filter_by(user_id=user_id).one().tier == "pro"
    try:
        assert_can_use(user_id, "computer", "director")
        raise AssertionError("expired pro must not open Pilot")
    except QuotaError as exc:
        assert exc.code == "plan"
    assert_can_use(user_id, "chat", "gpt-6-luna")
    manager.debit_plan_tokens(user_id, "chat", 1000)
    assert manager.get_subscription(user_id)["chat_tokens_used"] == 40

    manager.set_subscription_tier(user_id, "creator", 30)
    with SyncSessionLocal() as session:
        sub = session.query(Subscription).filter_by(user_id=user_id).one()
        sub.expires_at = 0
        session.commit()
    creator = usage_view(manager.get_subscription(user_id))
    assert creator["tier"] == "creator"
    assert creator["unlimited"] is True


def test_conversation_list_uses_db_active_flag_and_real_updated_at():
    manager = DatabaseConversationManager()
    repo = ConversationRepository()
    email = "audit-active-5758@example.com"
    user_id = repo._bot_id(email)
    quiet = manager.create_conversation(user_id, title="Тихий")
    current = manager.create_conversation(user_id, title="Текущий")
    try:
        with SyncSessionLocal() as session:
            row = session.get(Conversation, quiet.id)
            row.created_at = row.updated_at
            row.updated_at = row.created_at
            session.commit()
        from datetime import datetime, timezone

        with SyncSessionLocal() as session:
            row = session.get(Conversation, quiet.id)
            row.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
            row.updated_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
            session.commit()
        manager.add_message(user_id, "user", "я снова здесь", conv_id=quiet.id, author_user_id=user_id)
        view = manager.conversation_view(user_id, quiet.id)
        assert "2020" in view.created_at
        assert "2020" not in view.updated_at
        listing = asyncio.run(repo.get_conversations(email))
        by_id = {item["id"]: item for item in listing}
        assert by_id[current.id]["is_active"] is True
        assert by_id[quiet.id]["is_active"] is False
        assert by_id[quiet.id]["updated_at"] == view.updated_at
        assert by_id[quiet.id]["updated_at"] != by_id[quiet.id]["created_at"]
        recent = manager.recent_user_chats(user_id)
        assert recent.index("Тихий") < recent.index("Текущий")
    finally:
        _cleanup(quiet.id, current.id)


def test_free_quota_is_atomic_and_refunded_when_the_model_fails(monkeypatch):
    manager = DatabaseConversationManager()
    user_id = 975_800_007
    manager.get_subscription(user_id)
    with SyncSessionLocal() as session:
        sub = session.query(Subscription).filter_by(user_id=user_id).one()
        sub.tier = "free"
        sub.expires_at = 0
        sub.daily_gpt54 = 0
        session.commit()

    assert manager.consume_daily_counter(user_id, "daily_gpt54", 1) is True
    assert manager.consume_daily_counter(user_id, "daily_gpt54", 1) is False
    manager.refund_daily_counter(user_id, "daily_gpt54")
    assert manager.get_subscription(user_id)["daily_gpt54"] == 0

    won = []

    def worker():
        won.append(manager.consume_daily_counter(user_id, "daily_gpt54", 1))

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert won.count(True) == 1
    manager.refund_daily_counter(user_id, "daily_gpt54")

    repo = ConversationRepository()
    email = "audit-quota-5758@example.com"
    bot_id = repo._bot_id(email)
    conv = manager.create_conversation(bot_id, title="Квота")
    manager.set_user_model(bot_id, "gpt-6-luna")
    with SyncSessionLocal() as session:
        sub = session.query(Subscription).filter_by(user_id=bot_id).one()
        sub.tier = "free"
        sub.expires_at = 0
        sub.daily_gpt54 = 0
        session.commit()

    async def boom(*_args, **_kwargs):
        raise RuntimeError("model down")

    import config as bot_config

    bot_config.OPENAI_API_KEY = "sk-audit-test"
    monkeypatch.setattr("handlers.core.reduce_heavy_context", boom)

    async def silent(*_args, **_kwargs):
        return None

    from app.services.chat_service import run_chat

    try:
        try:
            asyncio.run(run_chat(email, "скажи одно слово", conv.id, silent, silent, silent))
            raise AssertionError("model failure should surface")
        except RuntimeError:
            pass
        assert manager.get_subscription(bot_id)["daily_gpt54"] == 0
        assert manager.conversation_view(bot_id, conv.id).messages == []
    finally:
        _cleanup(conv.id)


def test_refresh_token_is_not_accepted_as_access():
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    from app.auth import create_access_token, create_refresh_token, decode_token, get_current_user

    access = create_access_token({"sub": "audit-5758@example.com"})
    refresh = create_refresh_token({"sub": "audit-5758@example.com"})
    assert decode_token(access, expected_type="access")["type"] == "access"
    assert decode_token(refresh, expected_type="refresh")["type"] == "refresh"
    try:
        decode_token(refresh, expected_type="access")
        raise AssertionError("refresh token must not pass as access")
    except HTTPException as exc:
        assert exc.status_code == 401

    async def as_user():
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=refresh)
        await get_current_user(creds)

    try:
        asyncio.run(as_user())
        raise AssertionError("bearer refresh token must be rejected")
    except HTTPException as exc:
        assert exc.status_code == 401


def test_pending_job_is_rekeyed_and_a_second_pending_stream_is_refused():
    from app.services.generation_hub import GenerationHub

    async def scenario():
        hub = GenerationHub()
        started = asyncio.Event()

        async def work():
            started.set()
            await asyncio.sleep(30)

        senders = hub.bind("user-5758", None, job_key="pending:one")
        hub.start_task("user-5758", "pending:one", work())
        await started.wait()
        assert hub.is_running("user-5758", None) is True
        assert hub.has_pending("user-5758") is True
        extra = asyncio.sleep(30)
        try:
            hub.start_task("user-5758", "pending:two", extra)
            raise AssertionError("second pending stream must be refused")
        except RuntimeError:
            extra.close()
        await senders.send_meta("conv-real")
        assert hub.is_running("user-5758", "conv-real") is True
        assert hub.has_pending("user-5758") is False
        assert hub.get_job("user-5758", "pending:one") is None
        assert hub.cancel("user-5758", "conv-real") is True
        assert hub.cancel("user-5758", None) is False

    asyncio.run(scenario())


def test_conversation_id_retries_after_collision():
    manager = DatabaseConversationManager()
    user_id = 975_800_009
    state = {"n": 0}
    original = manager._conv_id

    first = manager.create_conversation(user_id, title="Первый")
    first_id = first.id

    def flaky():
        state["n"] += 1
        if state["n"] == 1:
            return first_id
        return original()

    manager._conv_id = flaky
    second_id = ""
    try:
        second = manager.create_conversation(user_id, title="Второй")
        second_id = second.id
        assert second.id != first.id
        assert state["n"] >= 2
    finally:
        manager._conv_id = original
        _cleanup(first.id, second_id)


def test_obscure_upload_paths_are_rejected():
    import os

    from fastapi.testclient import TestClient

    os.environ["SECRET_KEY"] = "audit-test-secret-key-not-default"
    os.environ["DEBUG"] = "true"
    get_settings.cache_clear()
    from app.main import app

    settings = get_settings()
    user_key = "a" * 16
    stored = "b" * 32 + ".png"
    folder = settings.UPLOAD_DIR / "chat" / user_key
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / stored
    target.write_bytes(b"png")
    client = TestClient(app)
    try:
        allowed = client.get(f"/uploads/chat/{user_key}/{stored}")
        assert allowed.status_code == 200
        assert allowed.headers["cache-control"] == "private, no-store"
        assert allowed.headers["x-content-type-options"] == "nosniff"
        guessed = client.get(f"/uploads/chat/{user_key}/secret.txt")
        assert guessed.status_code == 404
        assert client.get("/uploads/chat/not-a-user/file.png").status_code == 404
        source = settings.UPLOAD_DIR / "docgen_sources" / "1" / "abcdef.docx"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"docx")
        assert client.get("/uploads/docgen_sources/1/abcdef.docx").status_code == 404
        source.unlink(missing_ok=True)
    finally:
        target.unlink(missing_ok=True)
