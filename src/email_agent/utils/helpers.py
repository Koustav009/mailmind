import sys
from datetime import date, datetime, timezone

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def ensure_utf8_stdout() -> None:
    """Use UTF-8 for stdout — Windows consoles default to cp1252 and crash on email text."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def utcnow() -> datetime:
    """Current UTC time as a naive datetime (stored in SQLite as UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def format_imap_date(value: date) -> str:
    """Format a date as IMAP SEARCH SINCE expects (e.g. '05-Oct-2026')."""
    return f"{value.day:02d}-{_MONTHS[value.month - 1]}-{value.year}"


def truncate_text(text: str, max_chars: int) -> str:
    """Truncate text keeping the head and tail, with a marker in between."""
    if len(text) <= max_chars:
        return text
    marker = "\n\n[... truncated ...]\n\n"
    available = max_chars - len(marker)
    if available <= 0:
        return text[:max_chars]
    head_len = int(available * 0.75)
    tail_len = available - head_len
    return text[:head_len] + marker + text[-tail_len:]


def chunk_text(text: str, size: int) -> list[str]:
    """Split text into chunks of at most `size` characters."""
    if size <= 0:
        raise ValueError("size must be positive")
    return [text[i : i + size] for i in range(0, len(text), size)] or [""]
