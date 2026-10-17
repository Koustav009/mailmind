from email_agent.services.imap_service import parse_fetch_response, parse_uid_search


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
    uid, flags, raw = parse_fetch_response(lines)
    assert uid == 123
    assert flags == ["\\\\Seen", "\\\\Flagged"]
    assert raw == b"Hello\r\nWorld"


def test_parse_fetch_response_without_flags():
    lines = [
        b"1 (UID 55 BODY[] {3}",
        bytearray(b"abc"),
        b")",
    ]
    uid, flags, raw = parse_fetch_response(lines)
    assert uid == 55
    assert flags == []
    assert raw == b"abc"


def test_parse_fetch_response_empty():
    assert parse_fetch_response([b")"]) == (0, [], b"")
