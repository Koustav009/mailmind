import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class ProviderError(Exception):
    """Base LLM provider failure. `retryable` decides failover behaviour."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class ProviderRateLimitError(ProviderError):
    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class ProviderServerError(ProviderError):
    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class ProviderTimeoutError(ProviderError):
    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


class ProviderAuthError(ProviderError):
    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class ProviderResponseError(ProviderError):
    """Malformed or unusable provider output (e.g. invalid JSON)."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=True)


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class CompletionResult(Generic[T]):
    value: T
    provider: str
    model: str
    usage: Usage


def extract_json_object(text: str) -> dict:
    """Extract the first JSON object from model output (tolerates code fences)."""
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", candidate).strip()
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start, end = candidate.find("{"), candidate.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(candidate[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    raise ProviderResponseError(f"Model output is not a JSON object: {text[:200]!r}")


def parse_structured(text: str, response_model: type[T]) -> T:
    try:
        return response_model.model_validate(extract_json_object(text))
    except ValidationError as exc:
        raise ProviderResponseError(f"Output failed {response_model.__name__} validation: {exc}") from exc


class BaseProvider(ABC):
    """Abstract LLM provider: one chat completion against one model."""

    name: str = "base"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        model_strong: str | None = None,
        timeout: float = 45.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.model_strong = model_strong
        self.timeout = timeout

    def model_for_task(self, task: str) -> str:
        """Per-task model selection: 'strong' tasks get the upgraded model if set."""
        if task in ("summary", "summarization", "important") and self.model_strong:
            return self.model_strong
        return self.model

    @abstractmethod
    async def complete(
        self,
        messages: list[dict],
        response_model: type[T],
        *,
        task: str = "classification",
        temperature: float = 0.2,
        max_tokens: int = 1200,
    ) -> CompletionResult[T]:
        ...

    async def aclose(self) -> None:
        return None
