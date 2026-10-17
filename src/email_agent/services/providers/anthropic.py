from typing import TypeVar

import httpx
from pydantic import BaseModel

from email_agent.services.providers.base import (
    BaseProvider,
    CompletionResult,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderServerError,
    ProviderTimeoutError,
    Usage,
    parse_structured,
)

T = TypeVar("T", bound=BaseModel)

ANTHROPIC_BASE_URL = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(BaseProvider):
    """Anthropic Messages API provider."""

    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        model_strong: str | None = None,
        timeout: float = 45.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(api_key=api_key, model=model, model_strong=model_strong, timeout=timeout)
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def complete(
        self,
        messages: list[dict],
        response_model: type[T],
        *,
        task: str = "classification",
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> CompletionResult[T]:
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        chat = [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]
        payload: dict = {
            "model": self.model_for_task(task),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": chat,
        }
        if system:
            payload["system"] = system

        try:
            response = await self._client.post(
                f"{ANTHROPIC_BASE_URL}/messages",
                json=payload,
                headers={"x-api-key": self.api_key, "anthropic-version": ANTHROPIC_VERSION},
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"anthropic timed out: {exc}") from exc
        except httpx.TransportError as exc:
            raise ProviderServerError(f"anthropic transport error: {exc}") from exc

        if response.status_code == 429:
            raise ProviderRateLimitError(f"anthropic rate limited: {response.text[:200]}")
        if response.status_code in (401, 403):
            raise ProviderAuthError(f"anthropic auth failed ({response.status_code}): {response.text[:200]}")
        if response.status_code >= 500:
            raise ProviderServerError(f"anthropic server error ({response.status_code}): {response.text[:200]}")
        if response.status_code >= 400:
            raise ProviderError(
                f"anthropic request failed ({response.status_code}): {response.text[:200]}",
                retryable=False,
            )

        try:
            data = response.json()
            content = data["content"][0]["text"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderResponseError(f"Unexpected response shape from anthropic: {exc}") from exc

        usage_data = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=int(usage_data.get("input_tokens") or 0),
            completion_tokens=int(usage_data.get("output_tokens") or 0),
        )
        return CompletionResult(
            value=parse_structured(content, response_model),
            provider=self.name,
            model=payload["model"],
            usage=usage,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
