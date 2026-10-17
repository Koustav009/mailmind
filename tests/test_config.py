import pytest
from pydantic import ValidationError

from email_agent.config import Settings


def make_settings(**overrides) -> Settings:
    base = dict(
        imap_host="imap.example.com",
        imap_user="user@example.com",
        imap_password="secret",
        telegram_bot_token="token",
        telegram_chat_ids="123,456",
        llm_providers="groq,custom",
        groq_api_key="g-key",
        custom_api_key="c-key",
        custom_base_url="https://llm.example.com/v1",
    )
    base.update(overrides)
    return Settings(**base)


def test_provider_order_parsing():
    settings = make_settings()
    assert settings.provider_order == ["groq", "custom"]


def test_chat_id_whitelist_parsing():
    settings = make_settings()
    assert settings.chat_id_whitelist == {123, 456}


def test_sender_rule_parsing():
    settings = make_settings(sender_whitelist=" Boss@Example.com , @vip.example", sender_blacklist="spam@bad.example")
    assert settings.whitelist_rules == ["boss@example.com", "@vip.example"]
    assert settings.blacklist_rules == ["spam@bad.example"]


def test_enabled_provider_requires_api_key():
    with pytest.raises(ValidationError):
        make_settings(groq_api_key=None)


def test_unknown_provider_rejected():
    with pytest.raises(ValidationError):
        make_settings(llm_providers="groq,skynet", skynet_api_key="x")


def test_custom_provider_requires_base_url():
    with pytest.raises(ValidationError):
        make_settings(custom_base_url=None)
