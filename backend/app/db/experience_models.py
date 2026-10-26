"""Delivery receipts and anonymous, aggregated product measurements."""
from sqlalchemy import BigInteger, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class ChatSubmission(Base):
    __tablename__ = 'chat_submissions'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_email: Mapped[str] = mapped_column(String(320), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    generation_id: Mapped[str] = mapped_column(String(32))
    conversation_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[int] = mapped_column(BigInteger, index=True)


class ExperienceMetric(Base):
    __tablename__ = 'experience_metrics'
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(32), index=True)
    device: Mapped[str] = mapped_column(String(12))
    bucket: Mapped[int] = mapped_column(BigInteger, index=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(BigInteger, default=0)
    fast: Mapped[int] = mapped_column(Integer, default=0)
    medium: Mapped[int] = mapped_column(Integer, default=0)
    slow: Mapped[int] = mapped_column(Integer, default=0)
