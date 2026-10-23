"""Account-owned, explicitly published project knowledge, separate from chat history."""
from sqlalchemy import BigInteger, ForeignKey, String, Text, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[int] = mapped_column(BigInteger)


class ProjectChat(Base):
    __tablename__ = "project_chats"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)


class ProjectContextSettings(Base):
    __tablename__ = 'project_context_settings'
    conversation_id: Mapped[str] = mapped_column(ForeignKey('conversations.id', ondelete='CASCADE'), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'), index=True)
    policy: Mapped[str] = mapped_column(Text, default='{}')
    last_used: Mapped[str] = mapped_column(Text, default='[]')
    updated_at: Mapped[int] = mapped_column(BigInteger, default=0)


class ProjectEntry(Base):
    __tablename__ = "project_entries"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16))
    body: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(2048), default="")
    updated_at: Mapped[int] = mapped_column(BigInteger)


class ProjectRevision(Base):
    __tablename__ = "project_revisions"
    __table_args__ = (UniqueConstraint("entry_id", "number"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    entry_id: Mapped[str] = mapped_column(ForeignKey("project_entries.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(16))
    body: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(2048), default="")
    document_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    created_at: Mapped[int] = mapped_column(BigInteger)


class ProjectChunk(Base):
    __tablename__ = "project_chunks"
    __table_args__ = (UniqueConstraint("entry_id", "position"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    entry_id: Mapped[str] = mapped_column(ForeignKey("project_entries.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    folded: Mapped[str] = mapped_column(Text)
