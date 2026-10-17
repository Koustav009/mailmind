from email_agent.db.repositories import DecisionRepository, EmailRepository, UsageRepository


async def test_email_repository_roundtrip(session_factory):
    repo = EmailRepository(session_factory)
    assert await repo.exists("mid-1") is False

    await repo.add(
        message_id="mid-1",
        uid=42,
        subject="Hello",
        from_addr="alice@example.com",
        mail_date=None,
        classification={"importance": "high"},
    )
    assert await repo.exists("mid-1") is True

    record = await repo.get("mid-1")
    assert record is not None
    assert record.uid == 42
    assert record.classification == {"importance": "high"}
    assert record.action_taken == "pending"

    await repo.update_action("mid-1", "delete")
    assert (await repo.get("mid-1")).action_taken == "delete"

    await repo.set_telegram_message_id("mid-1", 987)
    assert (await repo.get("mid-1")).telegram_message_id == 987


async def test_update_missing_record_is_noop(session_factory):
    repo = EmailRepository(session_factory)
    await repo.update_action("missing", "delete")
    await repo.set_telegram_message_id("missing", 1)
    assert await repo.get("missing") is None


async def test_decision_repository(session_factory):
    repo = DecisionRepository(session_factory)
    await repo.record("mid-1", "delete")
    await repo.record("mid-2", "keep")
    decisions = await repo.list_all()
    assert [d.decision for d in decisions] == ["delete", "keep"]


async def test_usage_repository(session_factory):
    repo = UsageRepository(session_factory)
    await repo.record(provider="groq", model="llama", task="classification", prompt_tokens=10, completion_tokens=5)
