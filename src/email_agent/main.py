import asyncio
import signal

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from email_agent.config import Settings
from email_agent.db.repositories import DecisionRepository, EmailRepository, UsageRepository
from email_agent.db.session import init_db, make_engine, make_session_factory
from email_agent.log import configure_logging
from email_agent.services.action_service import ActionService
from email_agent.services.classifier import Classifier
from email_agent.services.imap_service import ImapService
from email_agent.services.llm_router import LLMRouter, build_providers
from email_agent.services.processor import EmailProcessor
from email_agent.services.telegram_service import TelegramService

log = structlog.get_logger(__name__)


class PollJob:
    """Scheduled inbox poll with heartbeat logging and failure alerting."""

    def __init__(
        self,
        processor: EmailProcessor,
        telegram: TelegramService,
        settings: Settings,
    ) -> None:
        self._processor = processor
        self._telegram = telegram
        self._settings = settings
        self.consecutive_failures = 0

    async def __call__(self) -> None:
        try:
            processed = await self._processor.run_cycle()
            self.consecutive_failures = 0
            log.info("poll_cycle_complete", processed=processed, heartbeat=True)
        except Exception as exc:
            self.consecutive_failures += 1
            log.error(
                "poll_cycle_failed",
                consecutive_failures=self.consecutive_failures,
                error=str(exc),
                exc_info=True,
            )
            if self.consecutive_failures >= self._settings.failures_before_alert:
                await self._telegram.send_alert(
                    f"Polling failed {self.consecutive_failures} times in a row: {exc}"
                )


async def run(settings: Settings) -> None:
    configure_logging(settings.log_level)
    log.info("agent_starting", providers=settings.provider_order)

    engine = make_engine(settings.database_url)
    await init_db(engine)
    session_factory = make_session_factory(engine)
    email_repo = EmailRepository(session_factory)
    decision_repo = DecisionRepository(session_factory)
    usage_repo = UsageRepository(session_factory)

    imap = ImapService(
        host=settings.imap_host,
        port=settings.imap_port,
        user=settings.imap_user,
        password=settings.imap_password,
        folder=settings.imap_folder,
        archive_folder=settings.imap_archive_folder,
        trash_folder=settings.imap_trash_folder,
    )
    await imap.connect()

    router = LLMRouter(
        build_providers(settings),
        max_retries=settings.llm_max_retries,
        strategy=settings.llm_strategy,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        usage_repo=usage_repo,
    )
    classifier = Classifier(router, settings)
    action_service = ActionService(imap, email_repo, decision_repo)
    telegram = TelegramService(
        bot_token=settings.telegram_bot_token,
        chat_ids=settings.chat_id_whitelist,
        primary_chat_id=settings.primary_chat_id,
        action_service=action_service,
        imap=imap,
        email_repo=email_repo,
    )
    await telegram.start()

    processor = EmailProcessor(imap, email_repo, classifier, telegram, settings)
    poll_job = PollJob(processor, telegram, settings)

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        poll_job,
        "interval",
        minutes=settings.poll_interval_minutes,
        max_instances=1,
        coalesce=True,
        jitter=30,
    )
    scheduler.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)
    except NotImplementedError:
        pass  # Windows: fall back to KeyboardInterrupt

    try:
        await poll_job()  # first cycle runs immediately
        await stop_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        log.info("agent_stopping")
        scheduler.shutdown(wait=False)
        await telegram.stop()
        await imap.disconnect()
        await router.aclose()
        await engine.dispose()
        log.info("agent_stopped")


def main() -> None:
    asyncio.run(run(Settings()))


if __name__ == "__main__":
    main()
