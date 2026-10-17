"""Phase 2/3 checkpoint: live router test with the real classification prompt.

Runs `router.complete(...)` with the production classify.txt system prompt and a
sample marketing email, then prints the validated classification JSON.

Requires a filled-in .env with at least one configured LLM provider.
"""

import asyncio

from email_agent.config import Settings
from email_agent.db.repositories import UsageRepository
from email_agent.db.session import make_engine, make_session_factory
from email_agent.models.classification import EmailClassification
from email_agent.services.classifier import PROMPT_PATH
from email_agent.services.llm_router import LLMRouter, build_providers
from email_agent.utils.helpers import ensure_utf8_stdout

SAMPLE_PROMPT = [
    {"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
    {
        "role": "user",
        "content": (
            "From: Shop Deals <deals@shop.example>\n"
            "Subject: 50% off this weekend!\n"
            "Date: 2026-10-17 10:00:00\n\n"
            "Body:\nOur biggest sale of the season! 50% off everything, this weekend only. "
            "Free shipping on orders over $50. Unsubscribe here. View in browser."
        ),
    },
]


async def main() -> None:
    ensure_utf8_stdout()
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
