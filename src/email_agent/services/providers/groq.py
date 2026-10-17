import httpx

from email_agent.services.providers.openai_compat import OpenAICompatProvider

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class GroqProvider(OpenAICompatProvider):
    """Groq exposes an OpenAI-compatible API; JSON mode is well supported."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        model_strong: str | None = None,
        timeout: float = 45.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            name="groq",
            api_key=api_key,
            base_url=GROQ_BASE_URL,
            model=model,
            model_strong=model_strong,
            timeout=timeout,
            json_mode=True,
            client=client,
        )
