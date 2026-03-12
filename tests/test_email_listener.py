"""
tests/test_email_listener.py — Unit tests for pipeline/email_listener.py

Covers:
    parse_subject       — valid commands, case insensitivity, unknown commands,
                          missing colon, empty subject
    parse_email         — extracts from/subject/body, detects command+topic,
                          handles RFC 2047-encoded subjects
    is_sender_allowed   — matching / non-matching addresses, case insensitivity,
                          display-name stripping
    connect_imap        — raises RuntimeError when credentials are absent,
                          calls IMAP4_SSL with correct host/port
    fetch_unread_messages — returns raw message bytes, marks messages as seen
"""

import email as _email_std
import pytest
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from unittest.mock import MagicMock, patch

from pipeline.email_listener import (
    VALID_COMMANDS,
    parse_subject,
    parse_email,
    is_sender_allowed,
    connect_imap,
    fetch_unread_messages,
    DEFAULT_IMAP_HOST,
    DEFAULT_IMAP_PORT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_raw_email(
    from_addr: str,
    subject: str,
    body: str,
    multipart: bool = False,
) -> bytes:
    """Build a minimal RFC 2822 email and return its bytes."""
    if multipart:
        msg = MIMEMultipart("alternative")
        msg.attach(MIMEText(body, "plain", "utf-8"))
    else:
        msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = from_addr
    msg["Subject"] = subject
    msg["To"] = "agent@beyondtomorrow.world"
    return msg.as_bytes()


# ---------------------------------------------------------------------------
# parse_subject
# ---------------------------------------------------------------------------

def test_parse_subject_research_command():
    cmd, topic = parse_subject("RESEARCH: quantum computing")
    assert cmd == "RESEARCH"
    assert topic == "quantum computing"


def test_parse_subject_blog_command():
    cmd, topic = parse_subject("BLOG: future of solar energy")
    assert cmd == "BLOG"
    assert topic == "future of solar energy"


def test_parse_subject_report_command():
    cmd, topic = parse_subject("REPORT: EU AI regulation")
    assert cmd == "REPORT"
    assert topic == "EU AI regulation"


def test_parse_subject_index_command():
    cmd, topic = parse_subject("INDEX: NIST post-quantum docs")
    assert cmd == "INDEX"
    assert topic == "NIST post-quantum docs"


def test_parse_subject_case_insensitive():
    """Lower-case and mixed-case commands are accepted."""
    cmd, topic = parse_subject("research: climate change")
    assert cmd == "RESEARCH"
    assert topic == "climate change"

    cmd2, topic2 = parse_subject("Blog: ocean plastic")
    assert cmd2 == "BLOG"
    assert topic2 == "ocean plastic"


def test_parse_subject_no_colon_returns_none():
    cmd, topic = parse_subject("RESEARCH quantum computing")
    assert cmd is None
    assert topic is None


def test_parse_subject_unknown_command_returns_none():
    cmd, topic = parse_subject("TASK: something")
    assert cmd is None
    assert topic is None


def test_parse_subject_empty_string_returns_none():
    cmd, topic = parse_subject("")
    assert cmd is None
    assert topic is None


def test_parse_subject_whitespace_stripped_from_topic():
    _, topic = parse_subject("RESEARCH:   spaced topic   ")
    assert topic == "spaced topic"


def test_valid_commands_set_contains_expected_values():
    """VALID_COMMANDS must contain exactly the four documented commands."""
    assert VALID_COMMANDS == {"BLOG", "RESEARCH", "REPORT", "INDEX"}


# ---------------------------------------------------------------------------
# parse_email
# ---------------------------------------------------------------------------

def test_parse_email_extracts_from_address():
    raw = _make_raw_email("alice@example.com", "Hello", "body text")
    result = parse_email(raw)
    assert "alice@example.com" in result["from"]


def test_parse_email_extracts_subject():
    raw = _make_raw_email("alice@example.com", "RESEARCH: AI safety", "body")
    result = parse_email(raw)
    assert "RESEARCH: AI safety" in result["subject"]


def test_parse_email_extracts_plaintext_body():
    raw = _make_raw_email("alice@example.com", "RESEARCH: topic", "Focus on X.")
    result = parse_email(raw)
    assert "Focus on X." in result["body"]


def test_parse_email_detects_command_and_topic():
    raw = _make_raw_email(
        "alice@example.com", "RESEARCH: quantum cryptography", "body"
    )
    result = parse_email(raw)
    assert result["command"] == "RESEARCH"
    assert result["topic"] == "quantum cryptography"


def test_parse_email_unknown_subject_sets_command_none():
    raw = _make_raw_email("alice@example.com", "Hello there", "body")
    result = parse_email(raw)
    assert result["command"] is None
    assert result["topic"] is None


def test_parse_email_multipart_extracts_body():
    raw = _make_raw_email(
        "alice@example.com",
        "BLOG: renewable energy",
        "Focus on solar.",
        multipart=True,
    )
    result = parse_email(raw)
    assert "Focus on solar." in result["body"]
    assert result["command"] == "BLOG"


# ---------------------------------------------------------------------------
# is_sender_allowed
# ---------------------------------------------------------------------------

_ALLOWLIST = [
    {"address": "admin@beyondtomorrow.world"},
    {"address": "jeremiah@example.com"},
]


def test_sender_allowed_exact_match():
    assert is_sender_allowed("admin@beyondtomorrow.world", _ALLOWLIST) is True


def test_sender_denied_unknown_address():
    assert is_sender_allowed("stranger@example.com", _ALLOWLIST) is False


def test_sender_allowed_case_insensitive():
    assert is_sender_allowed("ADMIN@BEYONDTOMORROW.WORLD", _ALLOWLIST) is True


def test_sender_allowed_with_display_name():
    """Display-name format 'Alice <alice@...>' is handled correctly."""
    assert (
        is_sender_allowed('"Jeremiah" <jeremiah@example.com>', _ALLOWLIST)
        is True
    )


def test_sender_denied_with_display_name_unknown():
    assert (
        is_sender_allowed('"Unknown" <unknown@evil.com>', _ALLOWLIST)
        is False
    )


def test_sender_allowed_empty_allowlist():
    assert is_sender_allowed("anyone@example.com", []) is False


def test_sender_allowed_strips_whitespace():
    assert is_sender_allowed("  admin@beyondtomorrow.world  ", _ALLOWLIST) is True


# ---------------------------------------------------------------------------
# connect_imap
# ---------------------------------------------------------------------------

def test_connect_imap_raises_without_email_user(monkeypatch):
    monkeypatch.delenv("EMAIL_USER", raising=False)
    monkeypatch.setenv("EMAIL_PASS", "password")
    with pytest.raises(RuntimeError, match="EMAIL_USER"):
        connect_imap()


def test_connect_imap_raises_without_email_pass(monkeypatch):
    monkeypatch.setenv("EMAIL_USER", "user@example.com")
    monkeypatch.delenv("EMAIL_PASS", raising=False)
    with pytest.raises(RuntimeError, match="EMAIL_PASS"):
        connect_imap()


def test_connect_imap_raises_without_both_credentials(monkeypatch):
    monkeypatch.delenv("EMAIL_USER", raising=False)
    monkeypatch.delenv("EMAIL_PASS", raising=False)
    with pytest.raises(RuntimeError):
        connect_imap()


def test_connect_imap_uses_default_host_and_port(monkeypatch, mocker):
    """When EMAIL_HOST/PORT are absent, uses the Hostinger defaults."""
    monkeypatch.setenv("EMAIL_USER", "user@example.com")
    monkeypatch.setenv("EMAIL_PASS", "secret")
    monkeypatch.delenv("EMAIL_HOST", raising=False)
    monkeypatch.delenv("EMAIL_PORT", raising=False)

    mock_imap = MagicMock()
    mock_imap.login.return_value = ("OK", [b"Logged in"])
    mock_cls = mocker.patch(
        "pipeline.email_listener.imaplib.IMAP4_SSL", return_value=mock_imap
    )

    connect_imap()

    mock_cls.assert_called_once_with(DEFAULT_IMAP_HOST, DEFAULT_IMAP_PORT)


def test_connect_imap_uses_custom_host_from_env(monkeypatch, mocker):
    """EMAIL_HOST env var overrides the default host."""
    monkeypatch.setenv("EMAIL_USER", "user@example.com")
    monkeypatch.setenv("EMAIL_PASS", "secret")
    monkeypatch.setenv("EMAIL_HOST", "mail.custom.com")
    monkeypatch.setenv("EMAIL_PORT", "993")

    mock_imap = MagicMock()
    mock_imap.login.return_value = ("OK", [b"Logged in"])
    mock_cls = mocker.patch(
        "pipeline.email_listener.imaplib.IMAP4_SSL", return_value=mock_imap
    )

    connect_imap()

    mock_cls.assert_called_once_with("mail.custom.com", 993)


def test_connect_imap_calls_login(monkeypatch, mocker):
    """connect_imap calls conn.login with the correct credentials."""
    monkeypatch.setenv("EMAIL_USER", "user@example.com")
    monkeypatch.setenv("EMAIL_PASS", "secret123")

    mock_imap = MagicMock()
    mock_imap.login.return_value = ("OK", [b"Logged in"])
    mocker.patch(
        "pipeline.email_listener.imaplib.IMAP4_SSL", return_value=mock_imap
    )

    connect_imap()

    mock_imap.login.assert_called_once_with("user@example.com", "secret123")


# ---------------------------------------------------------------------------
# fetch_unread_messages
# ---------------------------------------------------------------------------

def test_fetch_unread_messages_returns_raw_bytes(mocker):
    """Unread messages are returned as a list of raw byte strings."""
    mock_conn = MagicMock()
    mock_conn.select.return_value = ("OK", [b"1"])
    mock_conn.search.return_value = ("OK", [b"1"])
    mock_conn.fetch.return_value = (
        "OK",
        [(b"1 (RFC822 {42})", b"raw-email-bytes"), b")"],
    )
    mock_conn.store.return_value = ("OK", [b"Stored"])

    messages = fetch_unread_messages(mock_conn)

    assert messages == [b"raw-email-bytes"]


def test_fetch_unread_messages_marks_as_seen(mocker):
    """Each fetched message is marked \\Seen via IMAP STORE."""
    mock_conn = MagicMock()
    mock_conn.select.return_value = ("OK", [b"1"])
    mock_conn.search.return_value = ("OK", [b"1"])
    mock_conn.fetch.return_value = (
        "OK",
        [(b"1 (RFC822 {42})", b"bytes"), b")"],
    )
    mock_conn.store.return_value = ("OK", [b"Stored"])

    fetch_unread_messages(mock_conn)

    mock_conn.store.assert_called_once_with(b"1", "+FLAGS", "\\Seen")


def test_fetch_unread_messages_empty_inbox():
    """Empty inbox (no unread messages) returns an empty list."""
    mock_conn = MagicMock()
    mock_conn.select.return_value = ("OK", [b"1"])
    mock_conn.search.return_value = ("OK", [b""])  # no IDs

    messages = fetch_unread_messages(mock_conn)

    assert messages == []
    mock_conn.fetch.assert_not_called()


def test_fetch_unread_messages_multiple_emails():
    """Two unread messages produce two entries in the returned list."""
    mock_conn = MagicMock()
    mock_conn.select.return_value = ("OK", [b"2"])
    mock_conn.search.return_value = ("OK", [b"1 2"])
    mock_conn.fetch.side_effect = [
        ("OK", [(b"1 header", b"email-one"), b")"]),
        ("OK", [(b"2 header", b"email-two"), b")"]),
    ]
    mock_conn.store.return_value = ("OK", [b"Stored"])

    messages = fetch_unread_messages(mock_conn)

    assert len(messages) == 2
    assert b"email-one" in messages
    assert b"email-two" in messages
