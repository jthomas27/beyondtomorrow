"""Notifications workflow implementation."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from time import monotonic

from pipeline.paths import PROJECT_ROOT
from pipeline.workflows.common import _AGENT_TIMEOUT, _STAGE_COOLDOWN, _RETRY_BACKOFF_BASE

logger = logging.getLogger("pipeline")



def _send_pipeline_notification(subject: str, body: str) -> None:
    """Send a plain-text notification email to NOTIFY_EMAIL (if set).

    Uses Resend (RESEND_API_KEY) so outbound notifications never touch the
    Hostinger SMTP account — keeping it exclusively for inbound IMAP polling.
    Falls back to Hostinger SMTP only if RESEND_API_KEY is not set.
    Logs and swallows errors — a notification failure must never kill the pipeline.
    """
    import httpx as _httpx

    notify_email = os.environ.get("NOTIFY_EMAIL", "").strip()
    if not notify_email:
        return

    resend_key = os.environ.get("RESEND_API_KEY", "").strip()

    if resend_key:
        # --- Resend path (preferred) ---
        try:
            resp = _httpx.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
                json={
                    "from": "Beyond Tomorrow <admin@beyondtomorrow.world>",
                    "to": [notify_email],
                    "subject": subject,
                    "text": body,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                logger.info("Pipeline notification sent to %s via Resend: %s", notify_email, subject)
            else:
                logger.error("Resend notification failed (%s): %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            logger.error("Failed to send pipeline notification via Resend: %s", exc)
        return

    # --- Hostinger SMTP fallback (only if RESEND_API_KEY not set) ---
    import smtplib
    import email.mime.multipart
    import email.mime.text

    smtp_host = os.environ.get("SMTP_HOST", "smtp.hostinger.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER") or os.environ.get("EMAIL_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS") or os.environ.get("EMAIL_PASS", "")
    from_addr = smtp_user or "admin@beyondtomorrow.world"

    if not smtp_user or not smtp_pass:
        logger.warning("SMTP credentials not set and RESEND_API_KEY missing — skipping pipeline notification to %s", notify_email)
        return

    msg = email.mime.multipart.MIMEMultipart()
    msg["From"] = f"BeyondTomorrow.World <{from_addr}>"
    msg["To"] = notify_email
    msg["Subject"] = subject
    msg.attach(email.mime.text.MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, notify_email, msg.as_string())
        logger.info("Pipeline notification sent to %s via SMTP: %s", notify_email, subject)
    except Exception as exc:
        logger.error("Failed to send pipeline notification to %s: %s", notify_email, exc)

def _fmt_pipeline_stages(run_log) -> str:
    """Format stage summary lines from a PipelineRunLogger instance."""
    if run_log is None:
        return "  (no stage data)"
    summary = run_log.summary()
    stages = summary.get("stages", [])
    if not stages:
        return "  (no stage data)"
    lines = []
    for s in stages:
        status = s.get("status", "?").upper()
        name = s.get("stage", "?")
        elapsed = s.get("elapsed_s")
        elapsed_str = f" ({elapsed:.0f}s)" if elapsed is not None else ""
        lines.append(f"  {name:<14} {status}{elapsed_str}")
    return "\n".join(lines)
