from datetime import datetime

from pydantic import BaseModel, Field


class ParsedEmail(BaseModel):
    """Cleaned representation of a fetched email. Bodies are never persisted."""

    message_id: str
    uid: int = 0
    subject: str = ""
    from_addr: str = ""
    from_name: str = ""
    date: datetime | None = None
    body_text: str = ""
    is_html: bool = False
    has_attachments: bool = False

    @property
    def sender(self) -> str:
        return self.from_addr or self.from_name


class RawEmail(BaseModel):
    """Minimal metadata retained for on-demand actions (Show Full, delete)."""

    message_id: str
    uid: int
    subject: str = ""
    from_addr: str = Field(default="")
