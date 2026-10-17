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


class OpenAICompatProvider(BaseProvider):
    """Chat completions against any OpenAI-compatible endpoint (base_url + api_key).

    Covers OpenAI, OpenRouter, Together, Fireworks and custom gateways.
    """

    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        base_url: str,
        model: str,
        model_strong: str | None = None,
        timeout: float = 45.0,
        json_mode: bool = False,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(api_key=api_key, model=model, model_strong=model_strong, timeout=timeout)
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.json_mode = json_mode
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
        payload: dict = {
            "model": self.model_for_task(task),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"}

        data = await self._post("/chat/completions", payload, headers)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderResponseError(f"Unexpected response shape from {self.name}: {exc}") from exc
        usage = _usage_from(data.get("usage") or {})
        return CompletionResult(
            value=parse_structured(content, response_model),
            provider=self.name,
            model=payload["model"],
            usage=usage,
        )

    async def _post(self, path: str, payload: dict, headers: dict) -> dict:
        try:
            response = await self._client.post(f"{self.base_url}{path}", json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(f"{self.name} timed out: {exc}") from exc
        except httpx.TransportError as exc:
            raise ProviderServerError(f"{self.name} transport error: {exc}") from exc
        if response.status_code == 429:
            raise ProviderRateLimitError(f"{self.name} rate limited: {response.text[:200]}")
        if response.status_code in (401, 403):
            raise ProviderAuthError(f"{self.name} auth failed ({response.status_code}): {response.text[:200]}")
        if response.status_code >= 500:
            raise ProviderServerError(f"{self.name} server error ({response.status_code}): {response.text[:200]}")
        if response.status_code >= 400:
            raise ProviderError(
                f"{self.name} request failed ({response.status_code}): {response.text[:200]}",
                retryable=False,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderResponseError(f"{self.name} returned non-JSON body") from exc

    async def aclose(self) -> None:
        await self._client.aclose()


def _usage_from(usage: dict) -> Usage:
    return Usage(
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
    )
