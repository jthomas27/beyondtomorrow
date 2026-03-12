"""
pipeline/email_listener.py — IMAP email polling and task command parsing.

Connects to Hostinger IMAP to watch for incoming research trigger emails.
Only processes messages from approved senders (see config/allowlist.yaml).

Required env vars:
    EMAIL_HOST  — IMAP server hostname (default: imap.hostinger.com)
    EMAIL_PORT  — IMAP port (default: 993)
    EMAIL_USER  — IMAP username / email address
    EMAIL_PASS  — IMAP password

Email subject format:
    COMMAND: topic text here

Supported commands:
    BLOG      — full pipeline: research → write → edit → publish (draft)
    RESEARCH  — research only → saves structured notes to corpus
    REPORT    — research only → full Markdown report emailed back
    INDEX     — index attached PDF(s) into knowledge corpus
"""

import email
import imaplib
import os
from email.header import decode_header
from email.message import Message
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_COMMANDS = frozenset({"BLOG", "RESEARCH", "REPORT", "INDEX"})

DEFAULT_IMAP_HOST = "imap.hostinger.com"
DEFAULT_IMAP_PORT = 993


# ---------------------------------------------------------------------------
# Subject-line parser
# ---------------------------------------------------------------------------

def parse_subject(subject: str) -> tuple[Optional[str], Optional[str]]:
    """Parse a ``COMMAND: topic`` email subject.

    Returns ``(command, topic)`` when a recognised command prefix is found.
    Returns ``(None, None)`` when the subject cannot be parsed or the command
    is not in ``VALID_COMMANDS``.

    Comparisons are case-insensitive; the returned *command* is upper-cased.

    Args:
        subject: Raw subject string, e.g. ``"RESEARCH: quantum computing"``.
    """
    subject = subject.strip()
    if ":" not in subject:
        return None, None
    prefix, _, rest = subject.partition(":")
    command = prefix.strip().upper()
    if command not in VALID_COMMANDS:
        return None, None
    topic = rest.strip()
    return command, topic


# ---------------------------------------------------------------------------
# Email message parser
# ---------------------------------------------------------------------------

def _decode_mime_words(s: str) -> str:
    """Decode RFC 2047-encoded header words (e.g. ``=?UTF-8?b?...?=``)."""
    parts = decode_header(s)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _extract_body(msg: Message) -> str:
    """Extract the plain-text body from an ``email.message.Message`` object.

    For multipart messages, returns the first ``text/plain`` part that is not
    an attachment. Falls back to empty string if no suitable part is found.
    """
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                payload = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace") if payload else ""
        return ""
    payload = msg.get_payload(decode=True)
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace") if payload else ""


def parse_email(raw_message: bytes) -> dict:
    """Parse raw RFC 2822 email bytes into a structured dict.

    Returns::

        {
            "from":    str,          # sender address (may include display name)
            "subject": str,          # decoded subject line
            "body":    str,          # plain-text body
            "command": str | None,   # e.g. "RESEARCH"
            "topic":   str | None,   # e.g. "quantum computing"
        }
    """
    msg = email.message_from_bytes(raw_message)
    from_addr = msg.get("From", "")
    subject_raw = msg.get("Subject", "")
    subject = _decode_mime_words(subject_raw)
    body = _extract_body(msg)
    command, topic = parse_subject(subject)
    return {
        "from": from_addr,
        "subject": subject,
        "body": body,
        "command": command,
        "topic": topic,
    }


# ---------------------------------------------------------------------------
# Sender allowlist check
# ---------------------------------------------------------------------------

def is_sender_allowed(sender_email: str, allowlist: list[dict]) -> bool:
    """Return ``True`` if *sender_email* matches an entry in the allowlist.

    The comparison is case-insensitive. Display-name prefixes are stripped::

        '"Alice" <alice@example.com>'  →  'alice@example.com'

    Args:
        sender_email: The ``From`` header value (may include display name).
        allowlist: List of dicts with at least an ``"address"`` key, as loaded
            from ``config/allowlist.yaml`` ``allowed_senders``.
    """
    if "<" in sender_email and ">" in sender_email:
        sender_email = sender_email.split("<")[-1].rstrip(">")
    sender_email = sender_email.strip().lower()
    approved = {
        entry["address"].lower()
        for entry in allowlist
        if "address" in entry
    }
    return sender_email in approved


# ---------------------------------------------------------------------------
# IMAP connection helpers
# ---------------------------------------------------------------------------

def connect_imap() -> imaplib.IMAP4_SSL:
    """Open an authenticated IMAP4_SSL connection using env var credentials.

    Raises:
        RuntimeError: if ``EMAIL_USER`` or ``EMAIL_PASS`` are not set.
    """
    host = os.environ.get("EMAIL_HOST", DEFAULT_IMAP_HOST)
    port = int(os.environ.get("EMAIL_PORT", str(DEFAULT_IMAP_PORT)))
    user = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_PASS")

    if not user or not password:
        raise RuntimeError(
            "EMAIL_USER and EMAIL_PASS environment variables must be set "
            "to enable the email listener."
        )

    conn = imaplib.IMAP4_SSL(host, port)
    conn.login(user, password)
    return conn


def fetch_unread_messages(
    conn: imaplib.IMAP4_SSL,
    mailbox: str = "INBOX",
) -> list[bytes]:
    """Fetch all unread messages from *mailbox* and mark them as seen.

    Args:
        conn: An authenticated IMAP4_SSL connection (from :func:`connect_imap`).
        mailbox: The mailbox to check. Defaults to ``"INBOX"``.

    Returns:
        List of raw RFC 2822 message byte strings.
    """
    conn.select(mailbox)
    _, message_ids = conn.search(None, "UNSEEN")
    messages: list[bytes] = []
    for msg_id in message_ids[0].split():
        _, data = conn.fetch(msg_id, "(RFC822)")
        for part in data:
            if isinstance(part, tuple):
                messages.append(part[1])
        conn.store(msg_id, "+FLAGS", "\\Seen")
    return messages
