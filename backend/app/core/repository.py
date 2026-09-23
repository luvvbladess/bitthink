import asyncio
import hashlib
import logging
import re
import threading
from pathlib import Path
from typing import Any, Optional

import config as bot_config
import conversations
from app.config import get_settings

_PLACEHOLDER_TITLE_RE = re.compile(r"^(Новый чат|Новая беседа|Беседа #\d+)$")
logger = logging.getLogger(__name__)


def derive_conversation_title(content: str) -> str:
    first_line = next((line.strip() for line in (content or "").strip().splitlines() if line.strip()), "")
    if len(first_line) > 48:
        first_line = first_line[:48].rstrip() + "…"
    return first_line or "Новая беседа"


class ConversationRepository:
    """Adapter over the existing bot ConversationManager for web users."""

    def __init__(self) -> None:
        # Use the PostgreSQL-backed drop-in replacement.
        self._manager = conversations.DatabaseConversationManager()
        self._mutate_lock = threading.Lock()

    @staticmethod
    def _web_user_id_to_bot_id(web_user_id: str) -> int:
        """Deterministically map a web user id (email/username) to a bot integer id."""
        # Use a stable hash and offset to avoid collisions with real Telegram IDs
        digest = hashlib.sha256(web_user_id.encode()).hexdigest()
        return 1_000_000_000 + (int(digest[:12], 16) % 1_000_000_000)

    def _bot_id(self, web_user_id: str) -> int:
        return self._web_user_id_to_bot_id(web_user_id)

    async def notify_room(self, conv_id: Optional[str]) -> None:
        """Сообщить остальным участникам общего диалога, что история изменилась."""
        if not conv_id:
            return
        try:
            emails = await asyncio.to_thread(self._manager.participant_emails, conv_id)
            if not emails:
                return
            from app.services.generation_hub import hub

            payload = {"type": "conversation_sync", "payload": {"conversation_id": conv_id}}
            for email in emails:
                await hub.broadcast(email, payload)
        except Exception:
            logger.exception("Failed to notify shared conversation %s", conv_id)

    async def ensure_user(self, web_user_id: str, profile: Optional[dict] = None) -> int:
        bot_id = self._bot_id(web_user_id)
        # Ensure subscription record exists; web User/profile is managed by auth.py.
        await asyncio.to_thread(self._manager.get_subscription, bot_id)
        return bot_id

    async def get_profile(self, web_user_id: str) -> dict:
        bot_id = await self.ensure_user(web_user_id)
        return await asyncio.to_thread(self._manager.get_user_profile, bot_id)

    async def get_subscription(self, web_user_id: str) -> dict:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.get_subscription, bot_id)

    async def get_user_model(self, web_user_id: str) -> str:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.get_user_model, bot_id)

    async def set_user_model(self, web_user_id: str, model: str) -> None:
        bot_id = self._bot_id(web_user_id)
        await asyncio.to_thread(self._manager.set_user_model, bot_id, model)

    async def get_user_reasoning_effort(self, web_user_id: str) -> Optional[str]:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.get_user_reasoning_effort, bot_id)

    async def set_user_reasoning_effort(self, web_user_id: str, effort: Optional[str]) -> None:
        bot_id = self._bot_id(web_user_id)
        await asyncio.to_thread(self._manager.set_user_reasoning_effort, bot_id, effort)

    async def get_conversations(self, web_user_id: str) -> list[dict]:
        bot_id = self._bot_id(web_user_id)
        convs = await asyncio.to_thread(self._manager.get_conversations, bot_id)
        roles = await asyncio.to_thread(self._manager.conversation_roles, bot_id, [c.id for c in convs])
        return [
            {
                "id": c.id,
                "title": c.title,
                "created_at": c.created_at,
                "updated_at": c.created_at,
                "message_count": len(c.messages),
                "document_count": len(c.documents),
                "is_active": c.id == getattr(self._manager, "_active_conversations", {}).get(bot_id),
                "shared": c.id in roles,
                "role": roles.get(c.id, "owner"),
            }
            for c in convs
        ]

    async def create_conversation(self, web_user_id: str, title: Optional[str] = None) -> dict:
        bot_id = self._bot_id(web_user_id)
        conv = await asyncio.to_thread(self._manager.create_conversation, bot_id, title=title)
        return {
            "id": conv.id,
            "title": conv.title,
            "created_at": conv.created_at,
            "updated_at": conv.created_at,
            "message_count": 0,
            "document_count": 0,
            "is_active": True,
            "shared": False,
            "role": "owner",
        }

    async def set_active_conversation(self, web_user_id: str, conv_id: str) -> bool:
        bot_id = self._bot_id(web_user_id)
        result = await asyncio.to_thread(self._manager.set_active_conversation, bot_id, conv_id)
        return result is not None

    async def rename_conversation(self, web_user_id: str, conv_id: str, title: str) -> bool:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.rename_conversation, bot_id, conv_id, title)

    async def maybe_autotitle(self, web_user_id: str, conv_id: Optional[str], content: str) -> None:
        if not conv_id:
            return
        convs = await self.get_conversations(web_user_id)
        current = next((item for item in convs if item["id"] == conv_id), None)
        if not current or not _PLACEHOLDER_TITLE_RE.match(current.get("title") or ""):
            return
        source = (content or "").strip()
        if (current.get("message_count") or 0) > 1:
            messages = await self.get_messages(web_user_id, conv_id)
            first_user = next(
                (
                    item
                    for item in messages
                    if item.get("role") == "user" and (item.get("content") or "").strip()
                ),
                None,
            )
            if first_user:
                source = first_user["content"]
        await self.rename_conversation(web_user_id, conv_id, derive_conversation_title(source))

    async def delete_conversation(self, web_user_id: str, conv_id: str) -> bool:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.delete_conversation, bot_id, conv_id)

    async def clear_conversation(self, web_user_id: str, conv_id: str) -> bool:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.clear_conversation, bot_id, conv_id)

    def _get_messages_sync(self, bot_id: int, conv_id: Optional[str]) -> list[dict]:
        with self._mutate_lock:
            if conv_id:
                conv = self._manager.conversation_view(bot_id, conv_id)
            else:
                conv = self._manager.get_active_conversation(bot_id)
        if not conv:
            return []
        owner_id = self._manager.conversation_owner(conv.id)
        author_ids = [owner_id] if owner_id else []
        author_ids += [m.author_user_id for m in conv.messages if getattr(m, "author_user_id", None)]
        cards = self._manager.author_cards(author_ids)
        result = []
        for idx, msg in enumerate(conv.messages):
            content = msg.content
            search = getattr(msg, "search", None)
            if msg.role == "assistant":
                from kimi_client import extract_domain_sources, strip_source_links

                search = search or extract_domain_sources(content)
                if search:
                    content = strip_source_links(content)
            author_id = getattr(msg, "author_user_id", None)
            if msg.role == "user" and not author_id:
                author_id = owner_id
            author = cards.get(author_id) if msg.role == "user" and author_id else None
            result.append({
                "id": f"{conv.id}_{idx}",
                "role": msg.role,
                "content": content,
                "attachment": getattr(msg, "attachment", None),
                "search": search,
                "created_at": getattr(msg, "created_at", conv.created_at),
                "author": author,
                "mine": msg.role == "user" and author_id == bot_id,
            })
        return result

    async def get_messages(self, web_user_id: str, conv_id: Optional[str] = None) -> list[dict]:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._get_messages_sync, bot_id, conv_id)

    def _add_message_sync(
        self, bot_id: int, role: str, content: str, conv_id: Optional[str],
        attachment: Optional[dict] = None, search: Optional[list[dict]] = None,
    ) -> dict:
        with self._mutate_lock:
            if conv_id and role != "assistant":
                self._manager.set_active_conversation(bot_id, conv_id)
            msg = self._manager.add_message(
                bot_id, role, content, attachment=attachment, search=search,
                conv_id=conv_id, author_user_id=bot_id if role == "user" else None,
            )
            conv = self._manager.get_active_conversation(bot_id)
        return {
            "id": f"{conv.id}_{len(conv.messages) - 1}",
            "role": msg.role,
            "content": msg.content,
            "attachment": getattr(msg, "attachment", None),
            "search": getattr(msg, "search", None),
            "created_at": getattr(msg, "created_at", conv.created_at),
        }

    async def add_message(
        self, web_user_id: str, role: str, content: str, conv_id: Optional[str] = None,
        attachment: Optional[dict] = None, search: Optional[list[dict]] = None,
    ) -> dict:
        bot_id = self._bot_id(web_user_id)
        result = await asyncio.to_thread(self._add_message_sync, bot_id, role, content, conv_id, attachment, search)
        await self.notify_room(conv_id)
        return result

    def _get_messages_for_api_sync(self, bot_id: int, conv_id: Optional[str]) -> list[dict]:
        with self._mutate_lock:
            if conv_id:
                self._manager.set_active_conversation(bot_id, conv_id)
            return self._manager.get_messages_for_api(
                bot_id, bot_config.SYSTEM_PROMPT, requesting_user_id=bot_id, conv_id=conv_id,
            )

    async def get_messages_for_api(self, web_user_id: str, conv_id: Optional[str] = None) -> list[dict]:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._get_messages_for_api_sync, bot_id, conv_id)

    def _get_documents_sync(self, bot_id: int, conv_id: Optional[str]) -> list[dict]:
        return self._manager.get_documents(bot_id, conv_id=conv_id)

    async def get_documents(self, web_user_id: str, conv_id: Optional[str] = None) -> list[dict]:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._get_documents_sync, bot_id, conv_id)

    def _add_document_sync(self, bot_id: int, filename: str, content: str, conv_id: Optional[str]) -> None:
        self._manager.add_document(bot_id, filename, content, conv_id=conv_id)

    async def add_document(self, web_user_id: str, filename: str, content: str, conv_id: Optional[str] = None) -> None:
        bot_id = self._bot_id(web_user_id)
        await asyncio.to_thread(self._add_document_sync, bot_id, filename, content, conv_id)
        await self.notify_room(conv_id)

    def _remove_document_sync(self, bot_id: int, filename: str, conv_id: Optional[str]) -> bool:
        return self._manager.remove_document(bot_id, filename, conv_id=conv_id)

    async def remove_document(self, web_user_id: str, filename: str, conv_id: Optional[str] = None) -> bool:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._remove_document_sync, bot_id, filename, conv_id)

    async def remove_attachment(self, web_user_id: str, filename: str, conv_id: Optional[str] = None) -> Optional[dict]:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.remove_attachment, bot_id, filename, conv_id)

    def _clear_documents_sync(self, bot_id: int, conv_id: Optional[str]) -> bool:
        if conv_id:
            self._manager.set_active_conversation(bot_id, conv_id)
        return self._manager.clear_documents(bot_id)

    async def clear_documents(self, web_user_id: str, conv_id: Optional[str] = None) -> bool:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._clear_documents_sync, bot_id, conv_id)

    async def set_subscription_tier(
        self, web_user_id: str, tier: str, duration_days: int = 30, from_today: bool = False
    ) -> None:
        bot_id = self._bot_id(web_user_id)
        await asyncio.to_thread(self._manager.set_subscription_tier, bot_id, tier, duration_days, from_today)

    async def reset_non_admin_subscriptions(self, tier: str = "free", duration_days: int = 30) -> dict:
        return await asyncio.to_thread(self._manager.reset_non_admin_subscriptions, tier, duration_days)

    async def update_subscription_limits(self, web_user_id: str, field: str, value: int = 1) -> None:
        bot_id = self._bot_id(web_user_id)
        await asyncio.to_thread(self._manager.update_subscription_limits, bot_id, field, value)

    async def track_tokens(self, web_user_id: str, model: str, input_tokens: int = 0, output_tokens: int = 0) -> None:
        bot_id = self._bot_id(web_user_id)
        await asyncio.to_thread(self._manager.track_tokens, bot_id, model, input_tokens, output_tokens)

    async def track_image(self, web_user_id: str, model: str, count: int = 1) -> None:
        bot_id = self._bot_id(web_user_id)
        await asyncio.to_thread(self._manager.track_image, bot_id, model, count)

    async def get_day_usage(self, web_user_id: str, day: Optional[str] = None) -> dict:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.get_day_usage, bot_id, day)

    async def get_month_usage(self, web_user_id: str, month: Optional[str] = None) -> dict:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.get_month_usage, bot_id, month)

    async def delete_last_message(self, web_user_id: str, conv_id: str, role: str) -> bool:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.delete_last_message, bot_id, conv_id, role)

    async def truncate_messages(self, web_user_id: str, conv_id: str, keep_count: int) -> bool:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.truncate_after, bot_id, conv_id, keep_count)

    async def set_active_promocode(self, web_user_id: str, promocode: str) -> None:
        bot_id = self._bot_id(web_user_id)
        await asyncio.to_thread(self._manager.set_active_promocode, bot_id, promocode)

    async def get_custom_prompts(self, web_user_id: str) -> list[str]:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.get_custom_prompts, bot_id)

    async def add_custom_prompt(self, web_user_id: str, prompt: str) -> int:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.add_custom_prompt, bot_id, prompt)

    async def delete_custom_prompt(self, web_user_id: str, index: int) -> bool:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.delete_custom_prompt, bot_id, index)

    async def set_active_custom_prompt(self, web_user_id: str, index: Optional[int]) -> None:
        bot_id = self._bot_id(web_user_id)
        await asyncio.to_thread(self._manager.set_active_custom_prompt, bot_id, index)

    async def get_active_custom_prompt(self, web_user_id: str) -> Optional[str]:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.get_active_custom_prompt, bot_id)

    async def get_user_memory(self, web_user_id: str) -> dict:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.get_user_memory, bot_id)

    async def save_user_memory(self, web_user_id: str, **fields) -> dict:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.save_user_memory, bot_id, **fields)

    async def list_user_skills(self, web_user_id: str, enabled_only: bool = False) -> list[dict]:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.list_user_skills, bot_id, enabled_only)

    async def save_user_skill(self, web_user_id: str, **fields) -> dict | None:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.save_user_skill, bot_id, **fields)

    async def delete_user_skill(self, web_user_id: str, name: str) -> bool:
        bot_id = self._bot_id(web_user_id)
        return await asyncio.to_thread(self._manager.delete_user_skill, bot_id, name)


repo = ConversationRepository()
