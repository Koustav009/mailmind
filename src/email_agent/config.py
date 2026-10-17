from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROVIDER_NAMES = ("groq", "openai", "openrouter", "together", "fireworks", "anthropic", "custom")


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- IMAP ---
    imap_host: str
    imap_port: int = 993
    imap_user: str
    imap_password: str = Field(repr=False)
    imap_folder: str = "INBOX"
    imap_archive_folder: str = "Archive"
    imap_trash_folder: str = "Trash"
    imap_lookback_days: int = 2

    # --- Telegram ---
    telegram_bot_token: str = Field(repr=False)
    telegram_chat_ids: str = ""  # comma-separated whitelist of allowed chat ids

    # --- LLM router ---
    llm_providers: str = "groq,openrouter,custom"  # ordered priority list
    llm_timeout: float = 45.0
    llm_max_retries: int = 2
    llm_strategy: Literal["priority", "weighted"] = "priority"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1200

    groq_api_key: str | None = None
    groq_model: str = "llama-3.3-70b-versatile"
    groq_model_strong: str | None = None

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_model_strong: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"

    openrouter_api_key: str | None = None
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct"
    openrouter_model_strong: str | None = None

    together_api_key: str | None = None
    together_model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    together_model_strong: str | None = None

    fireworks_api_key: str | None = None
    fireworks_model: str = "accounts/fireworks/models/llama-v3p3-70b-instruct"
    fireworks_model_strong: str | None = None

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-5-haiku-latest"
    anthropic_model_strong: str | None = None

    custom_api_key: str | None = None
    custom_model: str = "gpt-4o-mini"
    custom_model_strong: str | None = None
    custom_base_url: str | None = None

    # --- Storage / runtime ---
    database_url: str = "sqlite+aiosqlite:///./data/agent.db"
    poll_interval_minutes: int = 5
    max_body_chars: int = 6000
    failures_before_alert: int = 3
    sender_whitelist: str = ""  # comma-separated emails or @domain
    sender_blacklist: str = ""
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _validate_providers(self) -> "Settings":
        unknown = [name for name in self._provider_order() if name not in PROVIDER_NAMES]
        if unknown:
            raise ValueError(f"Unknown LLM providers in LLM_PROVIDERS: {unknown}")
        for name in self._provider_order():
            if not getattr(self, f"{name}_api_key"):
                raise ValueError(f"LLM provider '{name}' is enabled but {name.upper()}_API_KEY is not set")
            if name == "custom" and not self.custom_base_url:
                raise ValueError("The 'custom' provider requires CUSTOM_BASE_URL")
        return self

    def _provider_order(self) -> list[str]:
        return [p.strip().lower() for p in self.llm_providers.split(",") if p.strip()]

    @property
    def provider_order(self) -> list[str]:
        return self._provider_order()

    @property
    def chat_id_whitelist(self) -> set[int]:
        return {int(x) for x in self.telegram_chat_ids.split(",") if x.strip()}

    @property
    def primary_chat_id(self) -> int | None:
        for value in self.telegram_chat_ids.split(","):
            if value.strip():
                return int(value.strip())
        return None

    @property
    def whitelist_rules(self) -> list[str]:
        return [x.strip().lower() for x in self.sender_whitelist.split(",") if x.strip()]

    @property
    def blacklist_rules(self) -> list[str]:
        return [x.strip().lower() for x in self.sender_blacklist.split(",") if x.strip()]
