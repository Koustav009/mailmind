from email_agent.models.classification import EmailClassification
from email_agent.models.email import ParsedEmail
from email_agent.services.telegram_service import (
    build_keyboard,
    format_notification,
    parse_callback_data,
    TelegramService,
)


class FakeActionService:
    def __init__(self, performed=True):
        self.calls = []
        self.performed = performed

    async def execute(self, message_id, action):
        self.calls.append((message_id, action))
        return self.performed


class FakeRecord:
    def __init__(self, message_id="mid-1", uid=42):
        self.message_id = message_id
        self.uid = uid
        self.action_taken = "pending"
        self.notify_token = "tok"
        self.telegram_message_id = 5
        self.classification = {}


class FakeRepo:
    def __init__(self, record):
        self.record = record

    async def get_by_notify_token(self, token):
        return self.record if self.record and self.record.notify_token == token else None


class FakeImap:
    def __init__(self):
        self.fetched = []

    async def fetch_message(self, uid):
        self.fetched.append(uid)
        return (
            b"Message-ID: <mid-1>\r\nFrom: <alice@example.com>\r\nSubject: S\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n\r\nfull body text\r\n"
        )


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))
        return type("Msg", (), {"message_id": len(self.sent)})()


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()


def make_service(action_service, repo, imap=None, chat_ids={100}, primary=100):
    service = TelegramService("token", chat_ids, primary, action_service, imap or FakeImap(), repo)
    service._app = FakeApp()
    return service


def make_classification() -> EmailClassification:
    return EmailClassification(
        importance="high",
        category="work",
        summary="Boss needs the report.",
        action_recommendation="notify",
        requires_confirmation=True,
        reason="Direct request from manager.",
        confidence=0.95,
    )


def test_format_notification_contains_key_fields():
    email = ParsedEmail(message_id="m", subject="Q3 Report", from_addr="boss@corp.example", from_name="Boss")
    text = format_notification(email, make_classification())
    assert "Q3 Report" in text
    assert "Boss <boss@corp.example>" in text
    assert "Boss needs the report." in text
    assert "Recommended: notify" in text
    assert "0.95" in text


def test_keyboard_and_callback_data_roundtrip():
    keyboard = build_keyboard("tok")
    buttons = [b for row in keyboard.inline_keyboard for b in row]
    assert [b.text for b in buttons] == ["Delete", "Archive", "Keep", "Show Full"]
    assert parse_callback_data(buttons[0].callback_data) == ("delete", "tok")
    assert parse_callback_data(buttons[1].callback_data) == ("archive", "tok")
    assert parse_callback_data(buttons[2].callback_data) == ("keep", "tok")
    assert parse_callback_data(buttons[3].callback_data) == ("show", "tok")
    assert parse_callback_data("bogus:tok") is None
    assert parse_callback_data("del:") is None


async def test_unauthorized_chat_is_rejected():
    actions = FakeActionService()
    service = make_service(actions, FakeRepo(FakeRecord()), chat_ids={100})
    answer = await service.handle_callback(999, "del:tok")
    assert answer == "Unauthorized"
    assert actions.calls == []


async def test_authorized_delete_dispatches_action():
    actions = FakeActionService(performed=True)
    service = make_service(actions, FakeRepo(FakeRecord()))
    answer = await service.handle_callback(100, "del:tok")
    assert answer == "Deleted (moved to Trash)"
    assert actions.calls == [("mid-1", "delete")]


async def test_already_handled_answer():
    actions = FakeActionService(performed=False)
    service = make_service(actions, FakeRepo(FakeRecord()))
    answer = await service.handle_callback(100, "arc:tok")
    assert answer == "Already handled"


async def test_unknown_token_is_rejected():
    actions = FakeActionService()
    service = make_service(actions, FakeRepo(None))
    answer = await service.handle_callback(100, "del:tok")
    assert answer == "Unknown message"
    assert actions.calls == []


async def test_show_full_sends_body_in_chunks():
    imap = FakeImap()
    service = make_service(FakeActionService(), FakeRepo(FakeRecord()), imap=imap)
    answer = await service.handle_callback(100, "show:tok")
    assert answer == "Full email sent"
    assert imap.fetched == [42]
    assert service._app.bot.sent == [(100, "full body text")]
