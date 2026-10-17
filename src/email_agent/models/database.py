from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from email_agent.utils.helpers import utcnow


class Base(DeclarativeBase):
    pass


class ProcessedEmail(Base):
    __tablename__ = "processed_emails"

    message_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    uid: Mapped[int] = mapped_column(Integer, default=0, index=True)
    subject: Mapped[str] = mapped_column(String(2048), default="")
    from_addr: Mapped[str] = mapped_column(String(512), default="")
    mail_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    classification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    action_taken: Mapped[str] = mapped_column(String(32), default="pending")
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notify_token: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, nullable=True)


class UserDecision(Base):
    __tablename__ = "user_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String(512), index=True)
    decision: Mapped[str] = mapped_column(String(32))
    decided_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProviderUsage(Base):
    __tablename__ = "provider_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(256))
    task: Mapped[str] = mapped_column(String(64))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
