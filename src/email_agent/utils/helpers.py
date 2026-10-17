from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current UTC time as a naive datetime (stored in SQLite as UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
