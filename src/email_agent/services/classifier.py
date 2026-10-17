from pathlib import Path

from email_agent.config import Settings
from email_agent.models.classification import EmailClassification
from email_agent.models.email import ParsedEmail
from email_agent.services.llm_router import LLMRouter
from email_agent.utils.helpers import truncate_text

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "classify.txt"


def sender_matches(from_addr: str, rules: list[str]) -> bool:
    """Match a sender against exact emails or @domain suffix rules."""
    addr = from_addr.strip().lower()
    for rule in rules:
        if rule.startswith("@"):
            if addr.endswith(rule):
                return True
        elif addr == rule:
            return True
    return False


def apply_sender_rules(
    classification: EmailClassification, from_addr: str, settings: Settings
) -> EmailClassification:
    """Override model output with configured whitelist/blacklist rules."""
    if sender_matches(from_addr, settings.whitelist_rules):
        return classification.model_copy(
            update={
                "importance": "high",
                "action_recommendation": "notify",
                "reason": f"[whitelisted sender] {classification.reason}",
            }
        )
    if sender_matches(from_addr, settings.blacklist_rules):
        return classification.model_copy(
            update={
                "importance": "low",
                "category": "spam",
                "action_recommendation": "delete",
                "requires_confirmation": True,
                "reason": f"[blacklisted sender] {classification.reason}",
            }
        )
    return classification


class Classifier:
    """Single-shot classification + summarization via the multi-LLM router."""

    def __init__(self, router: LLMRouter, settings: Settings) -> None:
        self._router = router
        self._settings = settings
        self._system_prompt = PROMPT_PATH.read_text(encoding="utf-8")

    async def classify(self, email: ParsedEmail) -> EmailClassification:
        body = truncate_text(email.body_text, self._settings.max_body_chars)
        user_message = (
            f"From: {email.from_name} <{email.from_addr}>\n"
            f"Subject: {email.subject}\n"
            f"Date: {email.date}\n\n"
            f"Body:\n{body}"
        )
        result = await self._router.complete(
            [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_message},
            ],
            EmailClassification,
            task="classification",
        )
        return apply_sender_rules(result.value, email.from_addr, self._settings)
