from email_agent.config import Settings
from email_agent.models.classification import EmailClassification
from email_agent.models.email import ParsedEmail
from email_agent.services.classifier import Classifier, apply_sender_rules, sender_matches
from email_agent.services.providers.base import CompletionResult, Usage


def make_settings(**overrides) -> Settings:
    base = dict(
        imap_host="imap.example.com",
        imap_user="user@example.com",
        imap_password="secret",
        telegram_bot_token="token",
        llm_providers="groq",
        groq_api_key="g-key",
    )
    base.update(overrides)
    return Settings(**base)


def make_classification(**overrides) -> EmailClassification:
    base = dict(
        importance="medium",
        category="promotion",
        summary="A sale announcement.",
        action_recommendation="archive",
        requires_confirmation=True,
        reason="Marketing content.",
        confidence=0.9,
    )
    base.update(overrides)
    return EmailClassification(**base)


class FakeRouter:
    def __init__(self, value: EmailClassification) -> None:
        self.value = value
        self.messages = None

    async def complete(self, messages, response_model, *, task="classification"):
        self.messages = messages
        return CompletionResult(value=self.value, provider="fake", model="fake-model", usage=Usage())


def make_email(body: str) -> ParsedEmail:
    return ParsedEmail(
        message_id="mid-1",
        uid=1,
        subject="Hello",
        from_addr="alice@example.com",
        from_name="Alice",
        body_text=body,
    )


async def test_classifier_builds_prompt_and_passes_through_model_output():
    router = FakeRouter(make_classification())
    classifier = Classifier(router, make_settings())
    email = make_email("Please review the attached report.")

    result = await classifier.classify(email)

    assert result.summary == "A sale announcement."
    assert router.messages[0]["role"] == "system"
    assert "unsubscribe" in router.messages[0]["content"].lower()
    user_message = router.messages[1]["content"]
    assert "Subject: Hello" in user_message
    assert "alice@example.com" in user_message
    assert "Please review the attached report." in user_message


async def test_classifier_truncates_long_bodies():
    settings = make_settings(max_body_chars=100)
    router = FakeRouter(make_classification())
    classifier = Classifier(router, settings)

    await classifier.classify(make_email("A" * 500 + "END"))

    user_message = router.messages[1]["content"]
    assert "truncated" in user_message
    assert len(user_message) < 500


async def test_whitelist_forces_high_importance():
    settings = make_settings(sender_whitelist="alice@example.com")
    classification = apply_sender_rules(make_classification(), "Alice@Example.com", settings)
    assert classification.importance == "high"
    assert classification.action_recommendation == "notify"
    assert classification.reason.startswith("[whitelisted sender]")


async def test_blacklist_forces_low_spam_delete():
    settings = make_settings(sender_blacklist="@shop.example")
    classification = apply_sender_rules(make_classification(), "deals@shop.example", settings)
    assert classification.importance == "low"
    assert classification.category == "spam"
    assert classification.action_recommendation == "delete"
    assert classification.requires_confirmation is True
    assert classification.reason.startswith("[blacklisted sender]")


async def test_unmatched_sender_keeps_model_output():
    settings = make_settings(sender_whitelist="boss@example.com", sender_blacklist="@spam.example")
    original = make_classification()
    classification = apply_sender_rules(original, "alice@example.com", settings)
    assert classification == original


def test_sender_matches_rules():
    assert sender_matches("a@b.example", ["a@b.example"])
    assert sender_matches("a@b.example", ["@b.example"])
    assert not sender_matches("a@b.example", ["@c.example"])
    assert not sender_matches("ab.example", ["b.example"])
