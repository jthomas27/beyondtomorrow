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
import signal
import smtplib
from email.header import decode_header
from email.message import Message
from typing import Optional

from pipeline.pipeline_logger import _write_entry as _log

logger = logging.getLogger("pipeline.email_listener")

# Load .env at module level so EMAIL_USER/EMAIL_PASS are available when the
# listener is run directly (e.g. python -m pipeline.email_listener locally).
# On Railway, env vars are injected by the platform and this is a no-op.
def _load_dotenv() -> None:
    """Load .env from the project root into os.environ (skips already-set vars)."""
    from pathlib import Path
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.is_file():
        return
    with open(env_path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value

_load_dotenv()

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


# ---------------------------------------------------------------------------
# Email body formatters
# ---------------------------------------------------------------------------

def _fmt_duration(elapsed_s: float) -> str:
    m, s = divmod(int(elapsed_s), 60)
    return f"{m}m {s}s" if m else f"{s}s"


def _fmt_stages(stages: list) -> str:
    lines = []
    for s in stages:
        icon = {"ok": "\u2713", "error": "\u2717", "skipped": "\u21B7"}.get(s["status"], "?")
        elapsed = f"  {s['elapsed_s']}s" if s.get("elapsed_s") else ""
        line = f"  {s['stage']:<12}{icon}{elapsed}"
        if s["status"] == "error":
            line += f"  ({s.get('error_type', 'Error')}: {s.get('error_message', '')})"
        elif s["status"] == "skipped":
            line += f"  ({s.get('reason', '')})"
        lines.append(line)
    return "\n".join(lines) if lines else "  (no stages recorded)"


def _fmt_linkedin_status(stages: list) -> str:
    """Extract a human-readable LinkedIn status line from the run_log stages list."""
    for stage in stages:
        if stage.get("stage") == "LinkedIn":
            li_status = stage.get("status")
            if li_status == "ok":
                result = stage.get("result", "")
                # Strip the "Personal: " prefix for brevity
                result = result.replace("Personal: ", "").strip()
                return f"LinkedIn : Posted — {result}"
            if li_status == "error":
                return f"LinkedIn : FAILED — {stage.get('error_message', 'unknown error')}"
            if li_status == "skipped":
                return f"LinkedIn : Skipped — {stage.get('reason', '')}"
    return ""


def _build_success_email(command: str, topic: str, result: dict) -> str:
    run_log = result.get("run_log")
    summary = run_log.summary() if run_log else {}
    duration = _fmt_duration(result.get("total_elapsed_s", 0))
    url = result.get("published_url", "https://beyondtomorrow.world")
    stage_lines = _fmt_stages(summary.get("stages", []))
    linkedin_line = _fmt_linkedin_status(summary.get("stages", []))
    return (
        f"Command  : {command}\n"
        f"Topic    : {topic}\n"
        f"Status   : Published\n"
        f"URL      : {url}\n"
        + (f"{linkedin_line}\n" if linkedin_line else "")
        + f"Duration : {duration}\n"
        f"\nStages:\n{stage_lines}"
    )


def _build_failure_email(command: str, topic: str, result: dict) -> str:
    run_log = result.get("run_log")
    summary = run_log.summary() if run_log else {}
    duration = _fmt_duration(result.get("total_elapsed_s", 0))
    failed_stage = summary.get("failed_stage") or "Unknown"
    error_type = summary.get("error_type") or "Error"
    error_msg = summary.get("error_message") or "Unknown error"
    run_id = summary.get("run_id", "")
    log_file = summary.get("log_file", "")
    stage_lines = _fmt_stages(summary.get("stages", []))
    cause_chain = summary.get("cause_chain")

    body = (
        f"Command  : {command}\n"
        f"Topic    : {topic}\n"
        f"Status   : FAILED at {failed_stage}\n"
        f"Error    : {error_type}: {error_msg}\n"
        f"Run ID   : {run_id}\n"
        f"Duration : {duration}\n"
        f"Log      : {log_file}\n"
        f"\nStages:\n{stage_lines}"
    )

    if cause_chain:
        body += "\n\nCause chain:"
        for c in cause_chain:
            body += f"\n  <- {c['type']}: {c['message']}"

    return body


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
            _log({"event": "email_ignored", "from": sender, "subject": parsed["subject"], "reason": "no_valid_command"})
            continue

        if not is_sender_allowed(sender, allowlist):
            logger.warning("Rejected email from unapproved sender: %s", sender)
            _log({"event": "email_rejected", "from": sender, "subject": parsed["subject"], "reason": "sender_not_in_allowlist"})
            continue

        task_str = f"{command}: {topic}"
        logger.info("Processing email task: %s (from %s)", task_str, sender)

        # Strip display name from sender to get plain address for reply
        reply_to = sender
        if "<" in sender and ">" in sender:
            reply_to = sender.split("<")[-1].rstrip(">")

        _log({"event": "email_received", "from": reply_to, "command": command, "topic": topic})
        # Acknowledge receipt immediately
        send_reply(
            reply_to,
            f"[BeyondTomorrow] Received: {command}: {topic}",
            f"Command  : {command}\nTopic    : {topic}\nStatus   : Processing",
        )

        try:
            result = await _run_blog_pipeline(task_str)
            if result.get("status") == "published":
                # Check whether LinkedIn also succeeded
                run_log_obj = result.get("run_log")
                summary = run_log_obj.summary() if run_log_obj else {}
                li_stage = next(
                    (s for s in summary.get("stages", []) if s.get("stage") == "LinkedIn"),
                    None,
                )
                li_failed = li_stage and li_stage.get("status") == "error"
                subject_suffix = " (LinkedIn failed)" if li_failed else ""
                logger.info("Task complete: %s%s", task_str, " [LinkedIn failed]" if li_failed else "")
                _log({
                    "event": "email_task_complete",
                    "command": command,
                    "topic": topic,
                    "url": result.get("published_url", ""),
                    "linkedin_ok": not li_failed,
                })
                send_reply(
                    reply_to,
                    f"[BeyondTomorrow] Published: {topic}{subject_suffix}",
                    _build_success_email(command, topic, result),
                )
            else:
                run_log = result.get("run_log")
                failed_stage = run_log.summary().get("failed_stage") if run_log else "Unknown"
                logger.error("Task failed: %s — stage: %s", task_str, failed_stage)
                _log({"event": "email_task_failed", "command": command, "topic": topic, "failed_stage": failed_stage})
                send_reply(
                    reply_to,
                    f"[BeyondTomorrow] Failed: {command}: {topic}",
                    _build_failure_email(command, topic, result),
                )
        except Exception as exc:
            logger.error("Task raised unhandled exception: %s — %s", task_str, exc, exc_info=True)
            _log({"event": "email_task_failed", "command": command, "topic": topic, "failed_stage": "unhandled", "error_type": type(exc).__name__, "error_message": str(exc)})
            send_reply(
                reply_to,
                f"[BeyondTomorrow] Failed: {command}: {topic}",
                (
                    f"Command  : {command}\n"
                    f"Topic    : {topic}\n"
                    f"Status   : FAILED (unhandled exception)\n"
                    f"Error    : {type(exc).__name__}: {exc}"
                ),
            )


async def run_poll_loop() -> None:
    """Run the email polling loop indefinitely.

    Also performs a startup scan of reports/ to index any new files, then
    re-scans on every poll cycle so new reports dropped into the folder are
    picked up automatically.
    """
    from pipeline.reports_watcher import scan_and_index_new_reports

    interval = int(os.environ.get("EMAIL_POLL_INTERVAL", str(DEFAULT_POLL_INTERVAL)))
    logger.info("Email listener starting — polling every %ds", interval)

    # Register the DB pool with the logger so all _write_entry calls persist to
    # PostgreSQL (shared with local runs), surviving Railway redeployments.
    _pool = None
    try:
        from pipeline.db import get_pool
        from pipeline.pipeline_logger import set_db_pool, mark_stale_runs_failed
        _pool = await get_pool()
        set_db_pool(_pool)
        logger.info("Pipeline logger connected to PostgreSQL.")
    except Exception as exc:
        logger.warning("DB pool init failed — pipeline logs will be file-only: %s", exc)

    # Stale-run janitor — auto-close any runs stuck as RUNNING from prior crashes.
    # stale_after_hours=0 catches any unterminated run; called at startup before
    # any new run_start is logged so there is no race condition.
    if _pool is not None:
        try:
            stale_ids = await mark_stale_runs_failed(_pool, stale_after_hours=0)
            if stale_ids:
                logger.warning(
                    "Stale-run janitor: closed %d orphaned run(s): %s",
                    len(stale_ids), ", ".join(stale_ids),
                )
            else:
                logger.info("Stale-run janitor: no orphaned runs found.")
        except Exception as _jex:
            logger.warning("Stale-run janitor error (non-fatal): %s", _jex)

    # Startup scan: index any reports/ files not yet in the corpus.
    try:
        await scan_and_index_new_reports()
    except Exception as exc:
        logger.error("Startup reports scan failed: %s", exc)

    # ------------------------------------------------------------------
    # SIGTERM handler — log run_failed for any in-progress run before exit
    # ------------------------------------------------------------------
    from time import monotonic as _monotonic

    _current_poll_task: asyncio.Task | None = None

    async def _shutdown_on_sigterm() -> None:
        from pipeline.pipeline_logger import get_active_run_log
        active = get_active_run_log()
        if active:
            # Find the stage that was started but never completed
            completed = {s["stage"] for s in active.stages}
            active_stage = "Unknown"
            for stage in active._stage_starts:
                if stage not in completed:
                    active_stage = stage
                    break
            else:
                if active.stages:
                    active_stage = active.stages[-1]["stage"]
            logger.warning(
                "SIGTERM received — logging run_failed for run %s at stage %s",
                active.run_id, active_stage,
            )
            active.run_failed(
                failed_stage=active_stage,
                exc=RuntimeError("SIGTERM — container killed by Railway"),
                total_elapsed_s=round(_monotonic() - active._pipeline_t0, 1),
            )
            # Allow the async DB write task to flush
            await asyncio.sleep(2)
        else:
            logger.info("SIGTERM received — no active run to log.")
        if _current_poll_task and not _current_poll_task.done():
            _current_poll_task.cancel()

    def _sigterm_callback() -> None:
        loop = asyncio.get_event_loop()
        loop.create_task(_shutdown_on_sigterm())

    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, _sigterm_callback)
        logger.debug("SIGTERM handler registered.")
    except (NotImplementedError, OSError):
        # Windows or environments where signal handling is unsupported
        logger.warning("Could not register SIGTERM handler (platform unsupported).")

    while True:
        try:
            _current_poll_task = asyncio.current_task()
            await poll_once()
        except asyncio.CancelledError:
            logger.info("Poll loop cancelled — shutting down.")
            break
        except Exception as exc:
            logger.error("Poll cycle error: %s", exc)

        # Re-scan reports/ each cycle to catch newly added files.
        try:
            await scan_and_index_new_reports()
        except Exception as exc:
            logger.error("Reports scan error: %s", exc)

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
