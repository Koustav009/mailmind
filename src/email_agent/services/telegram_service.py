from pathlib import Path

import structlog
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from email_agent.models.classification import EmailClassification
from email_agent.models.database import ProcessedEmail
from email_agent.models.email import ParsedEmail
from email_agent.services.action_service import ActionService
from email_agent.services.imap_service import ImapService
from email_agent.utils.email_parser import parse_email
from email_agent.utils.helpers import chunk_text

log = structlog.get_logger(__name__)

TELEGRAM_MESSAGE_LIMIT = 4000

IMPORTANCE_EMOJI = {"high": "\U0001f534", "medium": "\U0001f7e1", "low": "\U0001f7e2"}
CALLBACK_ACTIONS = {"del": "delete", "arc": "archive", "keep": "keep", "show": "show"}
ACTION_LABELS = {"delete": "Deleted (moved to Trash)", "archive": "Archived", "keep": "Kept in inbox"}
BUTTON_LABELS = {
    "del": "Delete",
    "arc": "Archive",
    "keep": "Keep",
    "show": "Show Full",
}


def format_notification(email: ParsedEmail, classification: EmailClassification) -> str:
    emoji = IMPORTANCE_EMOJI.get(classification.importance, "⚪")
    date_str = email.date.strftime("%Y-%m-%d %H:%M") if email.date else "unknown"
    return (
        f"{emoji} {classification.importance.capitalize()} — {classification.category}\n"
        f"Subject: {email.subject}\n"
        f"From: {email.from_name} <{email.from_addr}>\n"
        f"Date: {date_str}\n"
        f"Folder: {email.mail_folder or 'unknown'}\n\n"
        f"{classification.summary}\n\n"
        f"Reason: {classification.reason}\n"
        f"Confidence: {classification.confidence:.2f} | "
        f"Recommended: {classification.action_recommendation}"
    )


def build_keyboard(notify_token: str) -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(BUTTON_LABELS["del"], callback_data=f"del:{notify_token}"),
        InlineKeyboardButton(BUTTON_LABELS["arc"], callback_data=f"arc:{notify_token}"),
        InlineKeyboardButton(BUTTON_LABELS["keep"], callback_data=f"keep:{notify_token}"),
    ]
    return InlineKeyboardMarkup([row, [InlineKeyboardButton(BUTTON_LABELS["show"], callback_data=f"show:{notify_token}")]])


def parse_callback_data(data: str) -> tuple[str, str] | None:
    action, _, token = data.partition(":")
    if action in CALLBACK_ACTIONS and token:
        return CALLBACK_ACTIONS[action], token
    return None


class TelegramService:
    """Sends notifications with inline confirmation buttons and handles callbacks.

    Safety: callbacks are accepted ONLY from whitelisted chat ids; every
    destructive button press is an explicit confirmation.
    """

    def __init__(
        self,
        bot_token: str,
        chat_ids: set[int],
        primary_chat_id: int | None,
        action_service: ActionService,
        imap: ImapService,
        email_repo,
    ) -> None:
        self._token = bot_token
        self._chat_ids = chat_ids
        self._primary_chat_id = primary_chat_id
        self._action_service = action_service
        self._imap = imap
        self._email_repo = email_repo
        self._app: Application | None = None

    def build_application(self) -> Application:
        app = Application.builder().token(self._token).build()
        app.add_handler(CallbackQueryHandler(self._on_callback))
        return app

    async def start(self) -> None:
        self._app = self.build_application()
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling()
        log.info("telegram_started")

    async def stop(self) -> None:
        if self._app is None:
            return
        await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()
        self._app = None

    def is_authorized(self, chat_id: int | None) -> bool:
        return chat_id is not None and chat_id in self._chat_ids

    async def send_notification(
        self, email: ParsedEmail, classification: EmailClassification, notify_token: str
    ) -> int:
        if self._primary_chat_id is None or self._app is None:
            raise RuntimeError("Telegram is not configured/started")
        message = await self._app.bot.send_message(
            chat_id=self._primary_chat_id,
            text=format_notification(email, classification),
            reply_markup=build_keyboard(notify_token),
        )
        return message.message_id

    async def send_failure_notice(self, email: ParsedEmail) -> None:
        if self._primary_chat_id is None or self._app is None:
            return
        date_str = email.date.strftime("%Y-%m-%d %H:%M") if email.date else "unknown"
        await self._app.bot.send_message(
            chat_id=self._primary_chat_id,
            text=(
                "⚠️ Classification unavailable — please review manually.\n"
                f"Subject: {email.subject}\n"
                f"From: <{email.from_addr}>\n"
                f"Date: {date_str}"
            ),
        )

    async def send_alert(self, text: str) -> None:
        if self._primary_chat_id is None or self._app is None:
            return
        await self._app.bot.send_message(chat_id=self._primary_chat_id, text=f"⚠️ {text}")

    async def handle_callback(self, chat_id: int | None, data: str) -> str:
        """Process one button press. Returns the answer text shown to the user."""
        if not self.is_authorized(chat_id):
            log.warning("unauthorized_callback", chat_id=chat_id)
            return "Unauthorized"
        parsed = parse_callback_data(data)
        if parsed is None:
            return "Unknown action"
        action, token = parsed
        record = await self._email_repo.get_by_notify_token(token)
        if record is None:
            log.warning("callback_for_unknown_token")
            return "Unknown message"

        if action == "show":
            await self._send_full_body(record, chat_id)
            return "Full email sent"

        performed = await self._action_service.execute(record.message_id, action)
        label = ACTION_LABELS[action]
        return label if performed else "Already handled"

    async def _send_full_body(self, record: ProcessedEmail, chat_id: int) -> None:
        raw = await self._imap.fetch_message(record.uid)
        email = parse_email(raw, uid=record.uid)
        body = email.body_text or "(no text body)"
        for chunk in chunk_text(body, TELEGRAM_MESSAGE_LIMIT):
            await self._app.bot.send_message(chat_id=chat_id, text=chunk)

    async def _on_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        chat_id = query.message.chat_id if query.message else None
        answer = await self.handle_callback(chat_id, query.data or "")
        await query.answer(answer)
        if answer in ACTION_LABELS.values() and query.message is not None:
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception as exc:
                log.warning("keyboard_removal_failed", error=str(exc))
