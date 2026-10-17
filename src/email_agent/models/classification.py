from typing import Literal

from pydantic import BaseModel, Field


class EmailClassification(BaseModel):
    """Structured LLM output for a single email."""

    importance: Literal["high", "medium", "low"]
    category: Literal[
        "personal",
        "work",
        "promotion",
        "newsletter",
        "transaction",
        "spam",
        "notification",
        "other",
    ]
    summary: str
    action_recommendation: Literal["notify", "archive", "delete", "review"]
    requires_confirmation: bool
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
