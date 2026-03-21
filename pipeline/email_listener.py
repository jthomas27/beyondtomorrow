"""
pipeline/email_listener.py — IMAP email polling and task command parsing.

Connects to Hostinger IMAP to watch for incoming research trigger emails.
Only processes messages from approved senders (see config/allowlist.yaml).

Required env vars:
    EMAIL_HOST  — IMAP server hostname (default: imap.hostinger.com)
    EMAIL_PORT  — IMAP port (default: 993)
    EMAIL_USER  — IMAP username / email address
    EMAIL_PASS  — IMAP password

    SMTP_HOST   — SMTP server hostname (default: smtp.hostinger.com)
    SMTP_PORT   — SMTP port (default: 587)
    SMTP_USER   — SMTP username (default: same as EMAIL_USER)
    SMTP_PASS   — SMTP password (default: same as EMAIL_PASS)

Email subject format:
    COMMAND: topic text here

Supported commands:
    BLOG      — full pipeline: research → write → edit → publish (draft)
    RESEARCH  — research only → saves structured notes to corpus
    REPORT    — research only → full Markdown report emailed back
    INDEX     — index attached PDF(s) into knowledge corpus

Usage:
    # Run as a continuous polling daemon
    python -m pipeline.email_listener

    # The loop polls every POLL_INTERVAL seconds (default: 300 = 5 min).
    # Override with the EMAIL_POLL_INTERVAL env var.
"""

import asyncio
import email
import email.mime.text
import email.mime.multipart
import imaplib
import logging
import os
import smtplib
from email.header import decode_header
from email.message import Message
from typing import Optional

logger = logging.getLogger("pipeline.email_listener")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_COMMANDS = frozenset({"BLOG", "RESEARCH", "REPORT", "INDEX"})

DEFAULT_IMAP_HOST = "imap.hostinger.com"
DEFAULT_IMAP_PORT = 993
DEFAULT_SMTP_HOST = "smtp.hostinger.com"
DEFAULT_SMTP_PORT = 587


# ---------------------------------------------------------------------------
# SMTP reply helper
# ---------------------------------------------------------------------------

def send_reply(to_address: str, subject: str, body: str) -> None:
    """Send a plain-text status reply email to *to_address*.

    Uses SMTP credentials from environment variables. Logs and swallows
    any send errors so a notification failure never kills the main loop.

    Args:
        to_address: Recipient email address.
        subject:    Email subject line.
        body:       Plain-text message body.
    """
    smtp_host = os.environ.get("SMTP_HOST", DEFAULT_SMTP_HOST)
    smtp_port = int(os.environ.get("SMTP_PORT", str(DEFAULT_SMTP_PORT)))
    smtp_user = os.environ.get("SMTP_USER") or os.environ.get("EMAIL_USER")
    smtp_pass = os.environ.get("SMTP_PASS") or os.environ.get("EMAIL_PASS")
    from_addr = smtp_user or "admin@beyondtomorrow.world"

    if not smtp_user or not smtp_pass:
        logger.warning("SMTP credentials not set — skipping reply to %s", to_address)
        return

    msg = email.mime.multipart.MIMEMultipart()
    msg["From"] = f"BeyondTomorrow.World <{from_addr}>"
    msg["To"] = to_address
    msg["Subject"] = subject
    msg.attach(email.mime.text.MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, to_address, msg.as_string())
        logger.info("Reply sent to %s: %s", to_address, subject)
    except Exception as exc:
        logger.error("Failed to send reply to %s: %s", to_address, exc)


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


# ---------------------------------------------------------------------------
# Polling loop
# ---------------------------------------------------------------------------

DEFAULT_POLL_INTERVAL = 300  # seconds (5 minutes)


def _load_allowlist() -> list[dict]:
    """Load the approved-senders list from config/allowlist.yaml."""
    import yaml
    from pathlib import Path

    path = Path(__file__).parent.parent / "config" / "allowlist.yaml"
    if not path.exists():
        return []
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get("allowed_senders", [])


async def poll_once() -> None:
    """Check IMAP for new messages and dispatch any valid commands."""
    from pipeline.main import _run_blog_pipeline  # local import to avoid circular

    allowlist = _load_allowlist()

    try:
        conn = connect_imap()
    except Exception as exc:
        logger.error("IMAP connection failed: %s", exc)
        return

    try:
        raw_messages = fetch_unread_messages(conn)
    except Exception as exc:
        logger.error("Failed to fetch unread messages: %s", exc)
        return
    finally:
        try:
            conn.logout()
        except Exception:
            pass

    if not raw_messages:
        logger.debug("No new messages.")
        return

    for raw in raw_messages:
        parsed = parse_email(raw)
        sender = parsed["from"]
        command = parsed["command"]
        topic = parsed["topic"]

        if not command or not topic:
            logger.info("Ignoring email from %s — no valid command in subject.", sender)
            continue

        if not is_sender_allowed(sender, allowlist):
            logger.warning("Rejected email from unapproved sender: %s", sender)
            continue

        task_str = f"{command}: {topic}"
        logger.info("Processing email task: %s (from %s)", task_str, sender)

        # Strip display name from sender to get plain address for reply
        reply_to = sender
        if "<" in sender and ">" in sender:
            reply_to = sender.split("<")[-1].rstrip(">")

        # Acknowledge receipt immediately
        send_reply(
            reply_to,
            f"[BeyondTomorrow] Received: {command}: {topic}",
            f"Your request has been received and is now processing.\n\n"
            f"Command : {command}\n"
            f"Topic   : {topic}\n\n"
            f"The full pipeline (research → write → edit → publish) typically takes "
            f"5–15 minutes. You'll receive another email when it's done.\n\n"
            f"— BeyondTomorrow.World",
        )

        try:
            await _run_blog_pipeline(task_str)
            logger.info("Task complete: %s", task_str)
            send_reply(
                reply_to,
                f"[BeyondTomorrow] Published: {topic}",
                f"Your blog post has been published on BeyondTomorrow.World.\n\n"
                f"Topic   : {topic}\n"
                f"Status  : Published\n\n"
                f"Visit https://beyondtomorrow.world to read it live.\n\n"
                f"— BeyondTomorrow.World",
            )
        except Exception as exc:
            logger.error("Task failed: %s — %s", task_str, exc)
            send_reply(
                reply_to,
                f"[BeyondTomorrow] Failed: {command}: {topic}",
                f"Unfortunately your request encountered an error.\n\n"
                f"Command : {command}\n"
                f"Topic   : {topic}\n"
                f"Error   : {exc}\n\n"
                f"Please try sending the email again, or check the Railway logs for details.\n\n"
                f"— BeyondTomorrow.World",
            )


async def run_poll_loop() -> None:
    """Run the email polling loop indefinitely."""
    interval = int(os.environ.get("EMAIL_POLL_INTERVAL", str(DEFAULT_POLL_INTERVAL)))
    logger.info("Email listener starting — polling every %ds", interval)

    while True:
        try:
            await poll_once()
        except Exception as exc:
            logger.error("Poll cycle error: %s", exc)
        await asyncio.sleep(interval)


# ---------------------------------------------------------------------------
# CLI entry point:  python -m pipeline.email_listener
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )
    asyncio.run(run_poll_loop())
