"""Общий диалог: участник пишет и кладёт файл в беседу владельца, не в свою."""

from app.config import get_settings  # noqa: F401

from app.bot_core.db_conversations import DatabaseConversationManager


def test_member_writes_and_uploads_into_the_shared_conversation():
    manager = DatabaseConversationManager()
    owner = 880_001
    guest = 880_002
    owned = manager.create_conversation(owner, title="Комплект")
    manager.add_message(owner, "user", "исходное задание", conv_id=owned.id, author_user_id=owner)
    # У владельца после этого может открыться другой чат — общий не должен его забрать.
    other = manager.create_conversation(owner, title="Личный")

    token = manager.create_share(owner, owned.id)
    assert token
    assert manager.create_share(owner, owned.id) == token
    joined = manager.join_share(guest, token)
    assert joined["id"] == owned.id

    # Гость не переключает активную беседу владельца.
    assert manager.get_active_conversation(owner).id == other.id

    manager.add_message(guest, "user", "добавь акт", conv_id=owned.id, author_user_id=guest)
    manager.add_document(guest, "акт.txt", "текст акта", conv_id=owned.id)

    room = manager.conversation_view(guest, owned.id)
    assert [m.content for m in room.messages] == ["исходное задание", "добавь акт"]
    assert room.messages[1].author_user_id == guest
    assert manager.get_documents(guest, conv_id=owned.id) == [{"filename": "акт.txt", "content": "текст акта"}]
    # Личная активная беседа владельца пуста от чужих файлов.
    assert manager.get_documents(owner) == []

    guest_list = {c.id for c in manager.get_conversations(guest)}
    assert owned.id in guest_list
    assert manager.conversation_roles(guest, [owned.id])[owned.id] == "member"
    assert manager.conversation_roles(owner, [owned.id])[owned.id] == "owner"

    assert manager.revoke_share(owner, owned.id)
    assert manager.conversation_view(guest, owned.id) is None
    assert manager.join_share(guest, token) is None

    manager.delete_conversation(owner, owned.id)
    manager.delete_conversation(owner, other.id)
