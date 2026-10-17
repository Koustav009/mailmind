from email_agent.db.repositories import DecisionRepository, EmailRepository
from email_agent.services.action_service import ActionService


class FakeImap:
    def __init__(self):
        self.trash = []
        self.archived = []

    async def move_to_trash(self, uid):
        self.trash.append(uid)
        return True

    async def move_to_archive(self, uid):
        self.archived.append(uid)
        return True


async def store_email(repo: EmailRepository, message_id: str = "mid-1", uid: int = 42) -> None:
    await repo.add(
        message_id=message_id,
        uid=uid,
        subject="Hello",
        from_addr="alice@example.com",
        mail_date=None,
        classification={"importance": "high"},
        notify_token=f"tok-{message_id}",
    )


async def test_delete_moves_to_trash_and_records_decision(session_factory):
    email_repo = EmailRepository(session_factory)
    decision_repo = DecisionRepository(session_factory)
    imap = FakeImap()
    service = ActionService(imap, email_repo, decision_repo)
    await store_email(email_repo)

    assert await service.execute("mid-1", "delete") is True

    assert imap.trash == [42]
    assert imap.archived == []
    assert (await email_repo.get("mid-1")).action_taken == "delete"
    decisions = await decision_repo.list_all()
    assert [(d.message_id, d.decision) for d in decisions] == [("mid-1", "delete")]


async def test_repeat_action_is_idempotent(session_factory):
    email_repo = EmailRepository(session_factory)
    decision_repo = DecisionRepository(session_factory)
    imap = FakeImap()
    service = ActionService(imap, email_repo, decision_repo)
    await store_email(email_repo)

    assert await service.execute("mid-1", "archive") is True
    assert await service.execute("mid-1", "archive") is False
    assert await service.execute("mid-1", "delete") is False

    assert imap.archived == [42]
    assert imap.trash == []
    assert (await email_repo.get("mid-1")).action_taken == "archive"


async def test_keep_records_decision_without_imap(session_factory):
    email_repo = EmailRepository(session_factory)
    decision_repo = DecisionRepository(session_factory)
    imap = FakeImap()
    service = ActionService(imap, email_repo, decision_repo)
    await store_email(email_repo)

    assert await service.execute("mid-1", "keep") is True
    assert imap.trash == [] and imap.archived == []
    assert (await email_repo.get("mid-1")).action_taken == "keep"
    assert (await decision_repo.list_all())[0].decision == "keep"


async def test_unknown_message_and_invalid_action(session_factory):
    email_repo = EmailRepository(session_factory)
    service = ActionService(FakeImap(), email_repo, DecisionRepository(session_factory))

    assert await service.execute("missing", "delete") is False
    try:
        await service.execute("missing", "nuke")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
