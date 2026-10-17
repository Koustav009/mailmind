from dataclasses import dataclass, field

import pytest

from email_agent.config import Settings
from email_agent.models.classification import EmailClassification
from email_agent.services.processor import EmailProcessor


def make_settings(**overrides) -> Settings:
    base = dict(
        imap_host="imap.example.com",
        imap_user="user@example.com",
        imap_password="secret",
        telegram_bot_token="token",
        telegram_chat_ids="100",
        llm_providers="groq",
        groq_api_key="g-key",
    )
    base.update(overrides)
    return Settings(**base)


def raw_email(mid: str, body: str = "hello", from_addr: str = "alice@example.com") -> bytes:
    return (
        f"Message-ID: <{mid}>\r\nFrom: <{from_addr}>\r\nSubject: Test\r\n"
        f"Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
        f"Content-Type: text/plain; charset=utf-8\r\n\r\n{body}\r\n"
    ).encode()


def make_classification() -> EmailClassification:
    return EmailClassification(
        importance="medium",
        category="work",
        summary="Test summary.",
        action_recommendation="notify",
        requires_confirmation=True,
        reason="Test reason.",
        confidence=0.8,
    )


@dataclass
class FakeRecord:
    message_id: str
    uid: int = 0
    subject: str = ""
    from_addr: str = ""
    mail_date: object = None
    classification: dict | None = None
    action_taken: str = "pending"
    notify_token: str | None = None
    telegram_message_id: int | None = None


class FakeRepo:
    def __init__(self, events: list[str]):
        self.events = events
        self.records: dict[str, FakeRecord] = {}
        self.fail_add_for: set[str] = set()

    async def get(self, message_id):
        return self.records.get(message_id)

    async def add(self, **kwargs):
        self.events.append("repo.add")
        if kwargs["message_id"] in self.fail_add_for:
            raise RuntimeError("db down")
        self.records[kwargs["message_id"]] = FakeRecord(**kwargs)

    async def set_telegram_message_id(self, message_id, telegram_message_id):
        self.events.append("repo.set_tg")
        self.records[message_id].telegram_message_id = telegram_message_id


class FakeImap:
    def __init__(self, events: list[str], unseen: list[tuple[int, list[str], bytes]]):
        self.events = events
        self.unseen = unseen
        self.seen: list[int] = []

    async def fetch_unseen(self):
        self.events.append("imap.fetch")
        return self.unseen

    async def fetch_message(self, uid):
        return raw_email("mid-1")

    async def mark_seen(self, uid):
        self.events.append("imap.seen")
        self.seen.append(uid)


class FakeClassifier:
    def __init__(self, events: list[str], fail: bool = False):
        self.events = events
        self.fail = fail
        self.calls = 0

    async def classify(self, email):
        self.events.append("classify")
        self.calls += 1
        if self.fail:
            raise RuntimeError("all providers exhausted")
        return make_classification()


class FakeTelegram:
    def __init__(self, events: list[str], fail_notify: bool = False):
        self.events = events
        self.fail_notify = fail_notify
        self.notifications = []
        self.failures = []

    async def send_notification(self, email, classification, notify_token):
        self.events.append("tg.notify")
        if self.fail_notify:
            raise RuntimeError("telegram down")
        self.notifications.append((email.message_id, notify_token))
        return 77

    async def send_failure_notice(self, email):
        self.events.append("tg.failure")
        self.failures.append(email.message_id)


def make_processor(events, unseen, *, classifier=None, telegram=None, repo=None):
    settings = make_settings()
    return EmailProcessor(
        FakeImap(events, unseen),
        repo or FakeRepo(events),
        classifier or FakeClassifier(events),
        telegram or FakeTelegram(events),
        settings,
    )


async def test_happy_path_ordering_and_state():
    events: list[str] = []
    repo = FakeRepo(events)
    processor = make_processor(events, [(1, [], raw_email("mid-1"))], repo=repo)

    processed = await processor.run_cycle()

    assert processed == 1
    assert events.index("repo.add") < events.index("imap.seen")
    assert events.index("repo.add") < events.index("tg.notify")
    record = repo.records["mid-1"]
    assert record.classification["summary"] == "Test summary."
    assert record.telegram_message_id == 77
    assert record.action_taken == "pending"
    assert record.notify_token is not None


async def test_duplicate_message_id_is_skipped():
    events: list[str] = []
    repo = FakeRepo(events)
    classifier = FakeClassifier(events)
    unseen = [(1, [], raw_email("mid-1")), (2, [], raw_email("mid-1"))]
    processor = make_processor(events, unseen, classifier=classifier, repo=repo)

    processed = await processor.run_cycle()

    assert processed == 2
    assert classifier.calls == 1
    assert events.count("repo.add") == 1
    assert events.count("imap.seen") == 2


async def test_pending_notification_is_retried_then_marked_seen():
    events: list[str] = []
    repo = FakeRepo(events)
    repo.records["mid-1"] = FakeRecord(
        message_id="mid-1",
        uid=1,
        classification=make_classification().model_dump(),
        notify_token="tok-1",
    )
    telegram = FakeTelegram(events)
    processor = make_processor(events, [(1, [], raw_email("mid-1"))], telegram=telegram, repo=repo)

    await processor.run_cycle()

    assert events.count("classify") == 0
    assert telegram.notifications == [("mid-1", "tok-1")]
    assert repo.records["mid-1"].telegram_message_id == 77
    assert events[-1] == "imap.seen"


async def test_classification_failure_records_dead_letter_and_notifies():
    events: list[str] = []
    repo = FakeRepo(events)
    telegram = FakeTelegram(events)
    processor = make_processor(
        events,
        [(1, [], raw_email("mid-1"))],
        classifier=FakeClassifier(events, fail=True),
        telegram=telegram,
        repo=repo,
    )

    processed = await processor.run_cycle()

    assert processed == 1
    assert repo.records["mid-1"].action_taken == "error"
    assert repo.records["mid-1"].classification is None
    assert telegram.failures == ["mid-1"]
    assert events.index("repo.add") < events.index("imap.seen")


async def test_one_bad_email_does_not_block_the_queue():
    events: list[str] = []
    repo = FakeRepo(events)
    repo.fail_add_for = {"bad"}
    telegram = FakeTelegram(events)
    processor = make_processor(
        events,
        [(1, [], raw_email("bad")), (2, [], raw_email("good"))],
        telegram=telegram,
        repo=repo,
    )

    processed = await processor.run_cycle()

    assert processed == 1
    assert "good" in repo.records
    assert "bad" not in repo.records


async def test_notify_failure_keeps_record_pending_for_retry():
    events: list[str] = []
    repo = FakeRepo(events)
    telegram = FakeTelegram(events, fail_notify=True)
    processor = make_processor(events, [(1, [], raw_email("mid-1"))], telegram=telegram, repo=repo)

    with pytest.raises(RuntimeError):
        await processor.process_one(1, raw_email("mid-1"))

    record = repo.records["mid-1"]
    assert record.action_taken == "pending"
    assert record.telegram_message_id is None
