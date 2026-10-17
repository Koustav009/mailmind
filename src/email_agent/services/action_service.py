import structlog

from email_agent.db.repositories import DecisionRepository, EmailRepository
from email_agent.services.imap_service import ImapService

log = structlog.get_logger(__name__)

FINAL_ACTIONS = {"delete", "archive", "keep"}


class ActionService:
    """Executes user-confirmed actions against IMAP and records the decision.

    Every destructive action arrives here only after an explicit confirmation
    from a whitelisted Telegram chat. All operations are idempotent: acting on
    an already-decided message is a no-op.
    """

    def __init__(
        self,
        imap: ImapService,
        email_repo: EmailRepository,
        decision_repo: DecisionRepository,
    ) -> None:
        self._imap = imap
        self._email_repo = email_repo
        self._decision_repo = decision_repo

    async def execute(self, message_id: str, action: str) -> bool:
        """Perform `action` (delete|archive|keep). True if performed, False if no-op."""
        if action not in FINAL_ACTIONS:
            raise ValueError(f"Unknown action: {action}")
        record = await self._email_repo.get(message_id)
        if record is None:
            log.warning("action_for_unknown_message", message_id=message_id, action=action)
            return False
        if record.action_taken in FINAL_ACTIONS:
            log.info("action_already_decided", message_id=message_id, action=record.action_taken)
            return False

        if action == "delete":
            await self._imap.move_to_trash(record.uid)
        elif action == "archive":
            await self._imap.move_to_archive(record.uid)

        await self._email_repo.update_action(message_id, action)
        await self._decision_repo.record(message_id, action)
        log.info("action_executed", message_id=message_id, action=action, uid=record.uid)
        return True
