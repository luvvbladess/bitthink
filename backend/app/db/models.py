from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="user", nullable=False)
    bot_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan", lazy="selectin",
        order_by="Message.id",
    )
    documents: Mapped[list["Document"]] = relationship(
        "Document", back_populates="conversation", cascade="all, delete-orphan", lazy="selectin",
        order_by="Document.id",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    attachment: Mapped[str | None] = mapped_column(Text, nullable=True)
    search: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Кто написал реплику в общем диалоге. Пусто у ответов ассистента и у
    # старых сообщений личных чатов — там автор и есть владелец беседы.
    author_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")


class ConversationShare(Base):
    """Ссылка, по которой в беседу заходят другие люди."""

    __tablename__ = "conversation_shares"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConversationMember(Base):
    """Участник общего диалога. Владелец живёт в conversations.user_id и сюда не пишется."""

    __tablename__ = "conversation_members"
    __table_args__ = (UniqueConstraint("conversation_id", "user_id", name="uq_conversation_member"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EditorDocument(Base):
    """Документ беседы, открытый в OnlyOffice. Версия растёт с каждым сохранением:
    ключ key = id-version, и все, кто открыл ту же версию, правят её вместе."""

    __tablename__ = "editor_documents"
    __table_args__ = (UniqueConstraint("conversation_id", "filename"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ConversationAside(Base):
    """Переписка людей в беседе. Ассистент её не читает и не отвечает."""

    __tablename__ = "conversation_asides"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    author_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="documents")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    tier: Mapped[str] = mapped_column(String(32), default="free", nullable=False)
    expires_at: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    daily_nano_mini: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_gpt54: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_director: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_images: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_docs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_reset_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    has_used_trial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    active_promocode: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_reminded_date: Mapped[str | None] = mapped_column(String(255), nullable=True)
    selected_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reasoning_effort: Mapped[str | None] = mapped_column(String(16), nullable=True)
    period_start: Mapped[str | None] = mapped_column(String(32), nullable=True)
    chat_tokens_used: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    computer_tokens_used: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    images_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    nano_cushion_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    nano_cushion_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    session_started_at: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    session_chat_used: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    session_computer_used: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    week_start: Mapped[str | None] = mapped_column(String(32), nullable=True)
    week_chat_used: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    week_computer_used: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class CustomPrompt(Base):
    __tablename__ = "custom_prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserMemory(Base):
    __tablename__ = "user_memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    last_hash: Mapped[str] = mapped_column(String(32), default="", nullable=False)


class UserSkill(Base):
    __tablename__ = "user_skills"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_user_skills_user_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    description: Mapped[str] = mapped_column(String(180), default="", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    triggers: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    date: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    images: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cached_input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")


class AllowedContext(Base):
    __tablename__ = "allowed_contexts"

    context_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class BaseTemplate(Base):
    __tablename__ = "base_templates"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


class Connector(Base):
    """Encrypted Computer connector (Gmail, SSH, HTTP API, site login)."""

    __tablename__ = "connectors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    hint: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payload_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
