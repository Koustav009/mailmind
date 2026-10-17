import hashlib
import re
from datetime import datetime
from email import message_from_bytes, policy
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime
from email.utils import parseaddr

from bs4 import BeautifulSoup

from email_agent.models.email import ParsedEmail

_WHITESPACE_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def parse_email(raw: bytes, uid: int = 0, mail_folder: str = "") -> ParsedEmail:
    """Parse raw RFC822 bytes into a cleaned ParsedEmail."""
    msg = message_from_bytes(raw, policy=policy.default)
    from_name, from_addr = parseaddr(_header(msg, "from"))
    body_text, is_html = _extract_body(msg)
    return ParsedEmail(
        message_id=_message_id(msg, from_addr),
        uid=uid,
        subject=_header(msg, "subject"),
        from_addr=from_addr,
        from_name=from_name,
        date=_parse_date(msg),
        body_text=body_text,
        is_html=is_html,
        has_attachments=_has_attachments(msg),
        mail_folder=mail_folder,
    )


def _header(msg: Message, name: str) -> str:
    value = msg.get(name, "")
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def _parse_date(msg: Message) -> datetime | None:
    raw = msg.get("date")
    if not raw:
        return None
    try:
        parsed = parsedate_to_datetime(raw)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except (TypeError, ValueError):
        return None


def _message_id(msg: Message, from_addr: str) -> str:
    raw = (msg.get("message-id") or "").strip().strip("<>").strip()
    if raw:
        return raw
    seed = f"{from_addr}|{msg.get('date', '')}|{_header(msg, 'subject')}"
    return "generated-" + hashlib.sha256(seed.encode("utf-8", errors="replace")).hexdigest()[:32]


def _has_attachments(msg: Message) -> bool:
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            return True
    return False


def _extract_body(msg: Message) -> tuple[str, bool]:
    plain: str | None = None
    html: str | None = None
    for part in msg.walk():
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type == "text/plain" and plain is None:
            plain = _decode_part(part)
        elif content_type == "text/html" and html is None:
            html = _decode_part(part)
    if plain and plain.strip():
        return _clean_text(plain), False
    if html:
        return html_to_text(html), True
    return _clean_text(plain or ""), False


def _decode_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""
    charset = part.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def html_to_text(html: str) -> str:
    """Convert HTML to readable plain text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head", "title"]):
        tag.decompose()
    return _clean_text(soup.get_text(separator="\n"))


def _clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    cleaned = "\n".join(lines)
    return _BLANK_LINES_RE.sub("\n\n", cleaned).strip()
