from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from email_agent.models.database import ProcessedEmail, ProviderUsage, UserDecision


class EmailRepository:
    """Persistence for processed-email state (metadata + classification only)."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def exists(self, message_id: str) -> bool:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ProcessedEmail.message_id).where(ProcessedEmail.message_id == message_id)
            )
            return result.scalar_one_or_none() is not None

    async def get(self, message_id: str) -> ProcessedEmail | None:
        async with self._session_factory() as session:
            return await session.get(ProcessedEmail, message_id)

    async def add(
        self,
        *,
        message_id: str,
        uid: int,
        subject: str,
        from_addr: str,
        mail_date: datetime | None,
        classification: dict | None,
        action_taken: str = "pending",
        notify_token: str | None = None,
    ) -> None:
        async with self._session_factory() as session:
            session.add(
                ProcessedEmail(
                    message_id=message_id,
                    uid=uid,
                    subject=subject,
                    from_addr=from_addr,
                    mail_date=mail_date,
                    classification=classification,
                    action_taken=action_taken,
                    notify_token=notify_token,
                )
            )
            await session.commit()

    async def get_by_notify_token(self, token: str) -> ProcessedEmail | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ProcessedEmail).where(ProcessedEmail.notify_token == token)
            )
            return result.scalar_one_or_none()

    async def update_action(self, message_id: str, action_taken: str) -> None:
        async with self._session_factory() as session:
            record = await session.get(ProcessedEmail, message_id)
            if record is not None:
                record.action_taken = action_taken
                await session.commit()

    async def set_telegram_message_id(self, message_id: str, telegram_message_id: int) -> None:
        async with self._session_factory() as session:
            record = await session.get(ProcessedEmail, message_id)
            if record is not None:
                record.telegram_message_id = telegram_message_id
                await session.commit()


class DecisionRepository:
    """User confirmations kept for audit and future rule learning."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(self, message_id: str, decision: str) -> None:
        async with self._session_factory() as session:
            session.add(UserDecision(message_id=message_id, decision=decision))
            await session.commit()

    async def list_all(self) -> list[UserDecision]:
        async with self._session_factory() as session:
            result = await session.execute(select(UserDecision).order_by(UserDecision.id))
            return list(result.scalars().all())


class UsageRepository:
    """Centralized LLM token usage log."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(
        self,
        *,
        provider: str,
        model: str,
        task: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        async with self._session_factory() as session:
            session.add(
                ProviderUsage(
                    provider=provider,
                    model=model,
                    task=task,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )
            )
            await session.commit()
