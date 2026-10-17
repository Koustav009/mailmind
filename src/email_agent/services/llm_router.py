import asyncio
import random
from typing import TypeVar

import structlog
from pydantic import BaseModel

from email_agent.config import Settings
from email_agent.db.repositories import UsageRepository
from email_agent.services.providers.anthropic import AnthropicProvider
from email_agent.services.providers.base import (
    BaseProvider,
    CompletionResult,
    ProviderError,
    ProviderResponseError,
)
from email_agent.services.providers.groq import GroqProvider
from email_agent.services.providers.openai_compat import OpenAICompatProvider

T = TypeVar("T", bound=BaseModel)

log = structlog.get_logger(__name__)

OPENAI_COMPAT_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "together": "https://api.together.xyz/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "openai": "https://api.openai.com/v1",
}


class RouterExhaustedError(Exception):
    """Every configured provider failed for this request."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def build_provider(name: str, settings: Settings) -> BaseProvider:
    """Instantiate one provider from settings by name."""
    api_key = getattr(settings, f"{name}_api_key")
    model = getattr(settings, f"{name}_model")
    model_strong = getattr(settings, f"{name}_model_strong")
    if name == "groq":
        return GroqProvider(api_key=api_key, model=model, model_strong=model_strong, timeout=settings.llm_timeout)
    if name == "anthropic":
        return AnthropicProvider(api_key=api_key, model=model, model_strong=model_strong, timeout=settings.llm_timeout)
    if name == "custom":
        base_url = settings.custom_base_url or ""
    else:
        base_url = OPENAI_COMPAT_BASE_URLS[name]
    return OpenAICompatProvider(
        name=name,
        api_key=api_key,
        base_url=base_url,
        model=model,
        model_strong=model_strong,
        timeout=settings.llm_timeout,
        json_mode=name in ("openai",),
    )


def build_providers(settings: Settings) -> list[BaseProvider]:
    return [build_provider(name, settings) for name in settings.provider_order]


def _repair_message(response_model: type, exc: ProviderError) -> dict:
    return {
        "role": "user",
        "content": (
            "Your previous response was rejected:\n"
            f"{exc}\n\n"
            f"Respond again with ONLY one valid JSON object matching the required "
            f"{response_model.__name__} schema exactly - every field present, values "
            "only from the allowed literals. No markdown, no commentary."
        ),
    }


class LLMRouter:
    """Multi-provider completion with priority failover and central usage logging.

    Failover policy: retryable errors (rate limit, 5xx, timeout, bad output) are
    retried on the same provider up to `max_retries`, then the next provider in
    the configured order is tried. Non-retryable errors (auth, bad request) move
    to the next provider immediately.
    """

    def __init__(
        self,
        providers: list[BaseProvider],
        *,
        max_retries: int = 2,
        strategy: str = "priority",
        temperature: float = 0.2,
        max_tokens: int = 1200,
        usage_repo: UsageRepository | None = None,
    ) -> None:
        if not providers:
            raise ValueError("LLMRouter needs at least one provider")
        self._providers = providers
        self._max_retries = max_retries
        self._strategy = strategy
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._usage_repo = usage_repo

    async def complete(
        self,
        messages: list[dict],
        response_model: type[T],
        *,
        task: str = "classification",
    ) -> CompletionResult[T]:
        errors: list[str] = []
        for provider in self._order():
            attempt_messages = messages
            repaired = False
            for attempt in range(self._max_retries + 1):
                try:
                    result = await provider.complete(
                        attempt_messages,
                        response_model,
                        task=task,
                        temperature=self._temperature,
                        max_tokens=self._max_tokens,
                    )
                    await self._record_usage(result, task)
                    return result
                except ProviderError as exc:
                    errors.append(f"{provider.name}: {exc}")
                    log.warning(
                        "llm_provider_failed",
                        provider=provider.name,
                        attempt=attempt,
                        retryable=exc.retryable,
                        error=str(exc),
                    )
                    if not exc.retryable:
                        break
                    if isinstance(exc, ProviderResponseError) and not repaired:
                        attempt_messages = messages + [_repair_message(response_model, exc)]
                        repaired = True
                    if attempt < self._max_retries:
                        await asyncio.sleep(min(2**attempt, 8) + random.uniform(0, 0.5))
        raise RouterExhaustedError(errors)

    def _order(self) -> list[BaseProvider]:
        if self._strategy == "weighted" and len(self._providers) > 1:
            providers = list(self._providers)
            random.shuffle(providers)
            return providers
        return list(self._providers)

    async def _record_usage(self, result: CompletionResult, task: str) -> None:
        if self._usage_repo is None:
            return
        try:
            await self._usage_repo.record(
                provider=result.provider,
                model=result.model,
                task=task,
                prompt_tokens=result.usage.prompt_tokens,
                completion_tokens=result.usage.completion_tokens,
            )
        except Exception as exc:
            log.warning("usage_recording_failed", error=str(exc))

    async def aclose(self) -> None:
        for provider in self._providers:
            await provider.aclose()
