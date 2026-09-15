"""
Миграция существующих JSON-данных в PostgreSQL/SQLite.

Запуск:
    cd backend
    python -m scripts.migrate_json_to_pg

Перед запуском убедитесь, что DATABASE_URL указывает на целевую БД
и таблицы созданы (alembic upgrade head для PostgreSQL или запуск приложения
для SQLite).
"""

import asyncio
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.config import get_settings
from app.db.base import Base
from app.db.engine import AsyncSessionLocal, sync_engine
from app.db.models import (
    AllowedContext,
    BaseTemplate,
    Conversation,
    CustomPrompt,
    Document,
    Message,
    Subscription,
    UsageRecord,
    User,
)


def _bot_user_id(email: str) -> int:
    digest = hashlib.sha256(email.encode()).hexdigest()
    return 1_000_000_000 + (int(digest[:12], 16) % 1_000_000_000)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def migrate_users(users_file: Path) -> int:
    if not users_file.exists():
        return 0
    users = json.loads(users_file.read_text(encoding="utf-8"))
    count = 0
    async with AsyncSessionLocal() as session:
        for email, data in users.items():
            result = await session.execute(select(User).where(User.email == email))
            if result.scalar_one_or_none():
                continue
            session.add(User(
                email=email,
                password_hash=data.get("password_hash", ""),
                first_name=data.get("first_name"),
                role="user",
                bot_user_id=_bot_user_id(email),
            ))
            count += 1
        await session.commit()
    return count


async def migrate_bot_data(data_dir: Path) -> dict:
    stats = {"users": 0, "conversations": 0, "messages": 0, "documents": 0, "prompts": 0}
    if not data_dir.exists():
        return stats

    async with AsyncSessionLocal() as session:
        for user_file in sorted(data_dir.glob("user_*.json")):
            raw = json.loads(user_file.read_text(encoding="utf-8"))
            user_id = int(user_file.stem.split("_")[1])

            # Ensure a User row exists for this bot id (web or legacy telegram)
            result = await session.execute(select(User).where(User.bot_user_id == user_id))
            user = result.scalar_one_or_none()
            if not user:
                user = User(
                    email=f"legacy_{user_id}@local",
                    password_hash="",
                    first_name=f"User {user_id}",
                    role="user",
                    bot_user_id=user_id,
                )
                session.add(user)
                await session.flush()
                stats["users"] += 1

            # Subscription
            sub_data = raw.get("subscription", {})
            existing_sub = await session.execute(select(Subscription).where(Subscription.user_id == user_id))
            if not existing_sub.scalar_one_or_none():
                session.add(Subscription(
                    user_id=user_id,
                    tier=sub_data.get("tier", "free"),
                    expires_at=sub_data.get("expires_at", 0),
                    daily_nano_mini=sub_data.get("daily_nano_mini", 0),
                    daily_gpt54=sub_data.get("daily_gpt54", 0),
                    daily_director=sub_data.get("daily_director", 0),
                    daily_images=sub_data.get("daily_images", 0),
                    daily_docs=sub_data.get("daily_docs", 0),
                    last_reset_date=sub_data.get("last_reset_date"),
                    has_used_trial=sub_data.get("has_used_trial", False),
                    active_promocode=sub_data.get("active_promocode"),
                    last_reminded_date=sub_data.get("last_reminded_date"),
                    selected_model=raw.get("selected_model"),
                ))

            # Conversations / messages / documents
            active_conv_id = raw.get("active_conversation_id")
            for conv_raw in raw.get("conversations", []):
                conv_id = conv_raw["id"]
                conv = await session.execute(select(Conversation).where(Conversation.id == conv_id))
                if conv.scalar_one_or_none():
                    continue
                created_at = _parse_iso(conv_raw.get("created_at"))
                conversation = Conversation(
                    id=conv_id,
                    user_id=user_id,
                    title=conv_raw.get("title", "Беседа"),
                    is_active=(conv_id == active_conv_id),
                    created_at=created_at or datetime.utcnow(),
                    updated_at=created_at or datetime.utcnow(),
                )
                session.add(conversation)
                await session.flush()
                stats["conversations"] += 1

                for msg_raw in conv_raw.get("messages", []):
                    session.add(Message(
                        conversation_id=conv_id,
                        role=msg_raw.get("role", "user"),
                        content=msg_raw.get("content", ""),
                        created_at=_parse_iso(msg_raw.get("timestamp")) or datetime.utcnow(),
                    ))
                    stats["messages"] += 1

                for doc_raw in conv_raw.get("documents", []):
                    session.add(Document(
                        conversation_id=conv_id,
                        filename=doc_raw.get("filename", "document"),
                        content=doc_raw.get("content", ""),
                        created_at=datetime.utcnow(),
                    ))
                    stats["documents"] += 1

            # Custom prompts
            active_prompt = raw.get("active_custom_prompt")
            for idx, prompt_text in enumerate(raw.get("custom_prompts", [])):
                prompt = CustomPrompt(
                    user_id=user_id,
                    prompt=prompt_text,
                    active=(prompt_text == active_prompt),
                )
                session.add(prompt)
                stats["prompts"] += 1

            # Usage records
            for day, models in raw.get("token_usage", {}).items():
                for model, counts in models.items():
                    existing = await session.execute(
                        select(UsageRecord).where(
                            UsageRecord.user_id == user_id,
                            UsageRecord.date == day,
                            UsageRecord.model == model,
                        )
                    )
                    if existing.scalar_one_or_none():
                        continue
                    session.add(UsageRecord(
                        user_id=user_id,
                        date=day,
                        model=model,
                        input_tokens=counts.get("input") or 0,
                        output_tokens=counts.get("output") or 0,
                        images=counts.get("images") or 0,
                        calls=counts.get("calls") or 0,
                    ))

        # Allowed contexts
        contexts_file = data_dir / "allowed_contexts.json"
        if contexts_file.exists():
            contexts = json.loads(contexts_file.read_text(encoding="utf-8"))
            for context_id, allowed in contexts.items():
                existing = await session.execute(select(AllowedContext).where(AllowedContext.context_id == context_id))
                if not existing.scalar_one_or_none():
                    session.add(AllowedContext(context_id=context_id, allowed=bool(allowed)))

        await session.commit()
    return stats


async def main():
    settings = get_settings()
    print(f"DATABASE_URL: {settings.DATABASE_URL}")

    # Create tables for SQLite; for PostgreSQL use Alembic instead.
    if settings.DATABASE_URL.startswith("sqlite"):
        Base.metadata.create_all(bind=sync_engine)
        print("Created SQLite tables")

    project_root = settings.DATA_DIR.parent
    users_file = project_root / "backend" / "users.json"
    if not users_file.exists():
        users_file = project_root / "users.json"

    users_count = await migrate_users(users_file)
    print(f"Migrated {users_count} web users")

    stats = await migrate_bot_data(settings.DATA_DIR)
    print(f"Migration complete: {stats}")


if __name__ == "__main__":
    asyncio.run(main())
