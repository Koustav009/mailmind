from email_agent.services.imap_service import (
    mail_folder_from_labels,
    parse_fetch_response,
    parse_uid_search,
)


def test_parse_uid_search():
    assert parse_uid_search([b"1 2 3 42"]) == [1, 2, 3, 42]
    assert parse_uid_search([b""]) == []
    assert parse_uid_search([b"5", b"9"]) == [5, 9]


def test_parse_fetch_response_with_flags():
    lines = [
        b"7 (UID 123 FLAGS (\\\\Seen \\\\Flagged) BODY[] {12}",
        b"Hello\r\nWorld",
        b")",
    ]
    uid, flags, labels, raw = parse_fetch_response(lines)
    assert uid == 123
    assert flags == ["\\\\Seen", "\\\\Flagged"]
    assert labels == []
    assert raw == b"Hello\r\nWorld"


def test_parse_fetch_response_with_gm_labels():
    lines = [
        b'7 (UID 456 X-GM-LABELS (\\\\Inbox \\Important CATEGORY_PROMOTIONS) FLAGS (\\\\Seen) BODY[] {3}',
        b"abc",
        b")",
    ]
    uid, flags, labels, raw = parse_fetch_response(lines)
    assert uid == 456
    assert flags == ["\\\\Seen"]
    assert labels == ["\\\\Inbox", "\\Important", "CATEGORY_PROMOTIONS"]
    assert raw == b"abc"


def test_parse_fetch_response_without_flags():
    lines = [
        b"1 (UID 55 BODY[] {3}",
        bytearray(b"abc"),
        b")",
    ]
    uid, flags, labels, raw = parse_fetch_response(lines)
    assert uid == 55
    assert flags == []
    assert labels == []
    assert raw == b"abc"


def test_parse_fetch_response_empty():
    assert parse_fetch_response([b")"]) == (0, [], [], b"")


def test_mail_folder_from_labels():
    assert mail_folder_from_labels(["CATEGORY_PROMOTIONS"]) == "Promotions"
    assert mail_folder_from_labels(["CATEGORY_SOCIAL"]) == "Social"
    assert mail_folder_from_labels(["CATEGORY_UPDATES"]) == "Updates"
    assert mail_folder_from_labels(["CATEGORY_FORUMS"]) == "Forums"
    assert mail_folder_from_labels(["CATEGORY_PRIMARY"]) == "Primary"
    assert mail_folder_from_labels(["\\Inbox"]) == "Primary"
    assert mail_folder_from_labels([]) == "Primary"


def test_mail_folder_spam():
    assert mail_folder_from_labels(["[Gmail]/Spam"]) == "Spam"
    assert mail_folder_from_labels([], ["\\Seen", "\\Junk"]) == "Spam"
