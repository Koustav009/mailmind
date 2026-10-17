from datetime import date

from email_agent.utils.helpers import chunk_text, format_imap_date, truncate_text, utcnow


def test_format_imap_date_is_english_abbreviated():
    assert format_imap_date(date(2026, 10, 5)) == "05-Oct-2026"
    assert format_imap_date(date(2026, 1, 31)) == "31-Jan-2026"


def test_truncate_text_short_unchanged():
    assert truncate_text("hello", 10) == "hello"


def test_truncate_text_keeps_head_and_tail():
    text = "A" * 100 + "MIDDLE" + "B" * 100
    result = truncate_text(text, 60)
    assert len(result) <= 60
    assert result.startswith("A")
    assert result.endswith("B")
    assert "truncated" in result


def test_chunk_text():
    assert chunk_text("abcdef", 2) == ["ab", "cd", "ef"]
    assert chunk_text("", 5) == [""]


def test_utcnow_is_naive_utc():
    now = utcnow()
    assert now.tzinfo is None
