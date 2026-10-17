from email_agent.config import Settings
from email_agent.main import PollJob


class FakeProcessor:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = 0

    async def run_cycle(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("imap unreachable")
        return 3


class FakeTelegram:
    def __init__(self):
        self.alerts = []

    async def send_alert(self, text):
        self.alerts.append(text)


def make_settings(failures_before_alert: int = 3) -> Settings:
    return Settings(
        imap_host="imap.example.com",
        imap_user="user@example.com",
        imap_password="secret",
        telegram_bot_token="token",
        telegram_chat_ids="100",
        llm_providers="groq",
        groq_api_key="g-key",
        failures_before_alert=failures_before_alert,
    )


async def test_successful_cycle_heartbeat_without_alert():
    telegram = FakeTelegram()
    job = PollJob(FakeProcessor(), telegram, make_settings())
    await job()
    assert job.consecutive_failures == 0
    assert telegram.alerts == []


async def test_alert_after_consecutive_failures():
    telegram = FakeTelegram()
    job = PollJob(FakeProcessor(fail=True), telegram, make_settings(failures_before_alert=3))

    await job()
    await job()
    assert telegram.alerts == []
    await job()
    assert len(telegram.alerts) == 1
    assert "3 times" in telegram.alerts[0]

    await job()
    assert len(telegram.alerts) == 2


async def test_success_resets_failure_counter():
    telegram = FakeTelegram()
    failing = FakeProcessor(fail=True)
    job = PollJob(failing, telegram, make_settings(failures_before_alert=2))

    await job()
    failing.fail = False
    await job()
    assert job.consecutive_failures == 0

    failing.fail = True
    await job()
    assert telegram.alerts == []  # counter restarted after the success
