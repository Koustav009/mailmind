"""Phase 2 checkpoint: live router test across configured providers with failover.

Requires a filled-in .env with at least one configured LLM provider.
"""

import asyncio

from email_agent.config import Settings
from email_agent.db.session import make_engine, make_session_factory
from email_agent.models.classification import EmailClassification
from email_agent.db.repositories import UsageRepository
from email_agent.services.llm_router import LLMRouter, build_providers

SAMPLE_PROMPT = [
    {"role": "system", "content": "Classify the email. Respond with JSON only."},
    {
        "role": "user",
        "content": "From: deals@shop.example\nSubject: 50% off this weekend!\n\nUnsubscribe here. View in browser.",
    },
]


async def main() -> None:
    settings = Settings()
    engine = make_engine(settings.database_url)
    router = LLMRouter(
        build_providers(settings),
        max_retries=settings.llm_max_retries,
        strategy=settings.llm_strategy,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        usage_repo=UsageRepository(make_session_factory(engine)),
    )
    try:
        result = await router.complete(SAMPLE_PROMPT, EmailClassification, task="classification")
        print(f"provider={result.provider} model={result.model}")
        print(f"tokens: prompt={result.usage.prompt_tokens} completion={result.usage.completion_tokens}")
        print(result.value.model_dump_json(indent=2))
    finally:
        await router.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
