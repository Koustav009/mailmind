import httpx
import json
import pytest
from pydantic import BaseModel

from email_agent.config import Settings
from email_agent.services.llm_router import (
    RouterExhaustedError,
    LLMRouter,
    build_provider,
    build_providers,
)
from email_agent.services.providers.anthropic import AnthropicProvider
from email_agent.services.providers.base import extract_json_object
from email_agent.services.providers.groq import GroqProvider
from email_agent.services.providers.openai_compat import OpenAICompatProvider

MESSAGES = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]


class Item(BaseModel):
    name: str
    score: int


GOOD_JSON = '{"name": "x", "score": 1}'


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_delay):
        return None

    monkeypatch.setattr("email_agent.services.llm_router.asyncio.sleep", instant)


def chat_response(content: str, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
    )


def make_provider(name: str, handler) -> OpenAICompatProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatProvider(
        name=name,
        api_key=name,
        base_url="https://llm.test/v1",
        model="test-model",
        client=client,
    )


class FakeUsageRepo:
    def __init__(self):
        self.records = []

    async def record(self, **kwargs):
        self.records.append(kwargs)


async def test_failover_on_rate_limit():
    calls = {"p1": 0, "p2": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "p1" in str(request.headers.get("authorization", "")):
            calls["p1"] += 1
            return httpx.Response(429, json={"error": "rate limited"})
        calls["p2"] += 1
        return chat_response(GOOD_JSON)

    p1 = make_provider("p1", handler)
    p2 = make_provider("p2", handler)
    router = LLMRouter([p1, p2], max_retries=2)
    result = await router.complete(MESSAGES, Item)

    assert result.value == Item(name="x", score=1)
    assert result.provider == "p2"
    assert calls["p1"] == 3  # initial + 2 retries before failing over
    assert calls["p2"] == 1


async def test_retry_same_provider_on_server_error():
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(500, json={"error": "boom"})
        return chat_response(GOOD_JSON)

    router = LLMRouter([make_provider("p1", handler)], max_retries=2)
    result = await router.complete(MESSAGES, Item)
    assert result.provider == "p1"
    assert calls["count"] == 2


async def test_non_retryable_auth_moves_to_next_without_retry():
    calls = {"p1": 0, "p2": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if "p1" in str(request.headers.get("authorization", "")):
            calls["p1"] += 1
            return httpx.Response(401, json={"error": "bad key"})
        calls["p2"] += 1
        return chat_response(GOOD_JSON)

    router = LLMRouter([make_provider("p1", handler), make_provider("p2", handler)], max_retries=2)
    result = await router.complete(MESSAGES, Item)
    assert result.provider == "p2"
    assert calls["p1"] == 1


async def test_invalid_json_retries_then_fails_over():
    def p1_handler(request: httpx.Request) -> httpx.Response:
        return chat_response("not json at all")

    def p2_handler(request: httpx.Request) -> httpx.Response:
        return chat_response(f"```json\n{GOOD_JSON}\n```")

    router = LLMRouter([make_provider("p1", p1_handler), make_provider("p2", p2_handler)], max_retries=1)
    result = await router.complete(MESSAGES, Item)
    assert result.provider == "p2"
    assert result.value.name == "x"


async def test_parse_failure_triggers_repair_message():
    captured = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        if len(captured) == 1:
            return chat_response('{"category": "promotional"}')
        return chat_response(GOOD_JSON)

    router = LLMRouter([make_provider("p1", handler)], max_retries=1)
    result = await router.complete(MESSAGES, Item)

    assert result.value == Item(name="x", score=1)
    assert len(captured) == 2
    first, second = captured[0]["messages"], captured[1]["messages"]
    assert len(first) == len(MESSAGES)
    assert len(second) == len(MESSAGES) + 1
    repair = second[-1]
    assert repair["role"] == "user"
    assert "rejected" in repair["content"]
    assert "Item" in repair["content"]


async def test_exhausted_raises_with_all_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "down"})

    router = LLMRouter([make_provider("p1", handler), make_provider("p2", handler)], max_retries=1)
    with pytest.raises(RouterExhaustedError) as exc_info:
        await router.complete(MESSAGES, Item)
    errors = exc_info.value.errors
    assert len(errors) == 4  # 2 providers x (1 + 1 retries)
    assert any("p1" in e for e in errors)
    assert any("p2" in e for e in errors)


async def test_usage_is_recorded():
    repo = FakeUsageRepo()
    router = LLMRouter([make_provider("p1", lambda r: chat_response(GOOD_JSON))], usage_repo=repo)
    result = await router.complete(MESSAGES, Item, task="classification")
    assert result.usage.prompt_tokens == 10
    assert repo.records == [
        {"provider": "p1", "model": "test-model", "task": "classification", "prompt_tokens": 10, "completion_tokens": 5}
    ]


async def test_per_task_model_selection():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return chat_response(GOOD_JSON)

    provider = OpenAICompatProvider(
        name="p1",
        api_key="key",
        base_url="https://llm.test/v1",
        model="cheap-model",
        model_strong="strong-model",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    router = LLMRouter([provider])
    await router.complete(MESSAGES, Item, task="classification")
    assert captured["model"] == "cheap-model"
    await router.complete(MESSAGES, Item, task="summary")
    assert captured["model"] == "strong-model"


async def test_weighted_strategy_still_returns_valid_result():
    def handler(request: httpx.Request) -> httpx.Response:
        return chat_response(GOOD_JSON)

    router = LLMRouter([make_provider("p1", handler), make_provider("p2", handler)], strategy="weighted")
    result = await router.complete(MESSAGES, Item)
    assert result.value == Item(name="x", score=1)


async def test_anthropic_request_shape():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": GOOD_JSON}],
                "usage": {"input_tokens": 7, "output_tokens": 3},
            },
        )

    provider = AnthropicProvider(
        api_key="a-key",
        model="claude-test",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    router = LLMRouter([provider])
    result = await router.complete(MESSAGES, Item)

    assert result.value == Item(name="x", score=1)
    assert result.usage.prompt_tokens == 7
    assert result.usage.completion_tokens == 3
    body = captured["body"]
    assert body["system"] == "sys"
    assert body["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["request"].headers["x-api-key"] == "a-key"


def test_extract_json_object_variants():
    assert extract_json_object(GOOD_JSON) == {"name": "x", "score": 1}
    assert extract_json_object(f"```json\n{GOOD_JSON}\n```") == {"name": "x", "score": 1}
    assert extract_json_object(f"prefix {GOOD_JSON} suffix") == {"name": "x", "score": 1}


def test_build_providers_factory():
    settings = Settings(
        imap_host="imap.test",
        imap_user="u",
        imap_password="p",
        telegram_bot_token="t",
        llm_providers="groq,openai,openrouter,together,fireworks,anthropic,custom",
        groq_api_key="k",
        openai_api_key="k",
        openrouter_api_key="k",
        together_api_key="k",
        fireworks_api_key="k",
        anthropic_api_key="k",
        custom_api_key="k",
        custom_base_url="https://gateway.test/v1",
    )
    providers = build_providers(settings)
    assert [p.name for p in providers] == ["groq", "openai", "openrouter", "together", "fireworks", "anthropic", "custom"]
    assert isinstance(providers[0], GroqProvider)
    assert isinstance(providers[1], OpenAICompatProvider)
    assert providers[1].base_url == "https://api.openai.com/v1"
    assert providers[6].base_url == "https://gateway.test/v1"
    assert isinstance(build_provider("anthropic", settings), AnthropicProvider)
