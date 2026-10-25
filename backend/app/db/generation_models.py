"""Durable generation ownership, snapshots and cross-process delivery."""
from sqlalchemy import BigInteger, Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class Generation(Base):
    __tablename__ = 'generations'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_email: Mapped[str] = mapped_column(String(320), index=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    active_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), index=True)
    request: Mapped[str] = mapped_column(Text, default='{}')
    snapshot: Mapped[str] = mapped_column(Text, default='{}')
    owner: Mapped[str] = mapped_column(String(32), default='')
    lease_until: Mapped[int] = mapped_column(BigInteger, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[int] = mapped_column(BigInteger)


class GenerationEvent(Base):
    __tablename__ = 'generation_events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_email: Mapped[str] = mapped_column(String(320), index=True)
    publisher: Mapped[str] = mapped_column(String(32))
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(BigInteger, index=True)


class WorkerHeartbeat(Base):
    __tablename__ = 'worker_heartbeats'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    seen_at: Mapped[int] = mapped_column(BigInteger)
