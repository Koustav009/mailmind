import secrets
from datetime import date, timedelta

import structlog

from email_agent.config import Settings
from email_agent.db.repositories import EmailRepository
from email_agent.models.classification import EmailClassification
from email_agent.models.email import ParsedEmail
from email_agent.services.classifier import Classifier
from email_agent.services.imap_service import ImapService, mail_folder_from_labels
from email_agent.services.telegram_service import TelegramService
from email_agent.utils.email_parser import parse_email
from email_agent.utils.helpers import format_imap_date

log = structlog.get_logger(__name__)


class EmailProcessor:
    """Poll-cycle pipeline: fetch → dedupe → classify → store → notify → mark seen.

    Invariants:
    - A Message-ID is never processed twice (DB dedupe).
    - The DB write always precedes marking the message as \\Seen.
    - A classification failure is recorded as a dead letter and announced on
      Telegram; it never blocks processing of the remaining queue.
    """

    def __init__(
        self,
        imap: ImapService,
        email_repo: EmailRepository,
        classifier: Classifier,
        telegram: TelegramService,
        settings: Settings,
    ) -> None:
        self._imap = imap
        self._repo = email_repo
        self._classifier = classifier
        self._telegram = telegram
        self._settings = settings

    async def run_cycle(self) -> int:
        """Process unseen messages from the lookback window. Returns count processed."""
        since = format_imap_date(date.today() - timedelta(days=self._settings.imap_lookback_days))
        fetched = await self._imap.fetch_unseen(since=since)
        processed = 0
        for uid, _flags, labels, raw in fetched:
            try:
                await self.process_one(uid, raw, labels)
                processed += 1
            except Exception as exc:
                log.error("email_dead_letter", uid=uid, error=str(exc), exc_info=True)
        return processed

    async def process_one(self, uid: int, raw: bytes, labels: list[str] | None = None) -> None:
        email = parse_email(raw, uid=uid, mail_folder=mail_folder_from_labels(labels or []))
        record = await self._repo.get(email.message_id)
        if record is not None:
            await self._resend_pending_notification(record)
            await self._imap.mark_seen(uid)
            return

        notify_token = secrets.token_hex(8)
        try:
            classification = await self._classifier.classify(email)
        except Exception as exc:
            await self._store(email, classification=None, action_taken="error", notify_token=notify_token)
            await self._imap.mark_seen(uid)
            await self._telegram.send_failure_notice(email)
            log.error("classification_failed", message_id=email.message_id, error=str(exc))
            return

        await self._store(email, classification, action_taken="pending", notify_token=notify_token)
        await self._notify_and_link(email.message_id, email, classification, notify_token)
        await self._imap.mark_seen(uid)

    async def _resend_pending_notification(self, record) -> None:
        """Retry notification for a stored record whose Telegram send failed."""
        if record.telegram_message_id is not None or record.action_taken != "pending":
            return
        if not record.classification or not record.notify_token:
            return
        try:
            raw = await self._imap.fetch_message(record.uid)
            email = parse_email(raw, uid=record.uid)
            classification = EmailClassification(**record.classification)
            await self._notify_and_link(record.message_id, email, classification, record.notify_token)
        except Exception as exc:
            log.warning("notification_retry_failed", message_id=record.message_id, error=str(exc))

    async def _notify_and_link(
        self, message_id: str, email: ParsedEmail, classification: EmailClassification, notify_token: str
    ) -> None:
        telegram_message_id = await self._telegram.send_notification(email, classification, notify_token)
        await self._repo.set_telegram_message_id(message_id, telegram_message_id)

    async def _store(
        self,
        email: ParsedEmail,
        classification: EmailClassification | None,
        action_taken: str,
        notify_token: str,
    ) -> None:
        await self._repo.add(
            message_id=email.message_id,
            uid=email.uid,
            subject=email.subject,
            from_addr=email.from_addr,
            mail_date=email.date,
            classification=classification.model_dump() if classification else None,
            action_taken=action_taken,
            notify_token=notify_token,
        )
