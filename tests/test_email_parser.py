from email_agent.utils.email_parser import html_to_text, parse_email

RAW_PLAIN = (
    b"Message-ID: <abc123@example.com>\r\n"
    b"From: Alice Example <alice@example.com>\r\n"
    b"Subject: Hello world\r\n"
    b"Date: Mon, 01 Jan 2024 12:00:00 +0000\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"Hi Bob,\r\n\r\nThis is   a test.\r\n\r\n\r\n\r\nRegards\r\n"
)

RAW_HTML = (
    b"Message-ID: <html99@example.com>\r\n"
    b"From: marketing@shop.example\r\n"
    b"Subject: =?utf-8?B?SGVsbG8gw6kh?=\r\n"
    b"Date: Tue, 02 Jan 2024 09:30:00 +0000\r\n"
    b"MIME-Version: 1.0\r\n"
    b"Content-Type: text/html; charset=utf-8\r\n"
    b"\r\n"
    b"<html><head><style>body { color: red }</style><script>alert(1)</script></head>"
    b"<body><h1>Big Sale</h1><p>50% off &nbsp;today</p></body></html>"
)


def test_parse_plain_email():
    email = parse_email(RAW_PLAIN, uid=7)
    assert email.message_id == "abc123@example.com"
    assert email.uid == 7
    assert email.subject == "Hello world"
    assert email.from_addr == "alice@example.com"
    assert email.from_name == "Alice Example"
    assert email.date is not None
    assert email.is_html is False
    assert "Hi Bob," in email.body_text
    assert "This is a test." in email.body_text
    assert "\n\n\n" not in email.body_text


def test_parse_html_email_decodes_subject_and_strips_scripts():
    email = parse_email(RAW_HTML)
    assert email.subject == "Hello é!"
    assert email.is_html is True
    assert "Big Sale" in email.body_text
    assert "50% off today" in email.body_text
    assert "alert" not in email.body_text
    assert "color: red" not in email.body_text


def test_message_id_fallback_is_deterministic():
    raw = RAW_PLAIN.replace(b"Message-ID: <abc123@example.com>\r\n", b"")
    first = parse_email(raw)
    second = parse_email(raw)
    assert first.message_id.startswith("generated-")
    assert first.message_id == second.message_id


def test_html_to_text_basic():
    assert html_to_text("<p>a</p><p>b</p>") == "a\nb"
