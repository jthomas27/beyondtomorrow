#!/usr/bin/env python3
"""scripts/notify_pipeline_result.py

Sends a pipeline completion notification email via Hostinger SMTP.
Called by .github/workflows/agents.yml on every run (success or failure).

Required env vars (set as GitHub Actions secrets):
    SMTP_USER   — sender address (e.g. admin@beyondtomorrow.world)
    SMTP_PASS   — Hostinger email password
    NOTIFY_EMAIL — recipient address (set as a GitHub secret)

Usage:
    python scripts/notify_pipeline_result.py \\
        --to jeremiah.thomas2701@gmail.com \\
        --status success \\
        --event schedule \\
        --topic1 "Physical and transition climate risks" \\
        --topic2 "Prompting and AI skills" \\
        --topic3 "US-China technology decoupling" \\
        --run-url "https://github.com/owner/repo/actions/runs/12345"
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _build_subject(status: str, event: str) -> str:
    icon = "✓" if status == "success" else "✗"
    label = "completed" if status == "success" else "FAILED"
    trigger = "weekly schedule" if event == "schedule" else "manual dispatch"
    return f"[BeyondTomorrow] {icon} Pipeline {label} — {trigger}"


def _build_body(
    status: str,
    event: str,
    topics: list[str],
    task: str,
    run_url: str,
) -> str:
    lines = []

    if status == "success":
        lines.append("The BeyondTomorrow research pipeline completed successfully.")
    else:
        lines.append("The BeyondTomorrow research pipeline encountered an error.")

    lines += ["", f"Trigger : {'Weekly schedule (Saturday)' if event == 'schedule' else 'Manual dispatch'}"]
    lines += [f"Status  : {'SUCCESS ✓' if status == 'success' else 'FAILED ✗'}"]

    if event == "schedule" and any(topics):
        lines += ["", "Topics researched:"]
        for t in topics:
            if t:
                lines.append(f"  • {t}")
    elif task:
        lines += ["", f"Task: {task}"]

    if status != "success":
        lines += ["", "One or more pipeline steps failed. Check the Actions log for the full error."]

    if run_url:
        lines += ["", f"View run: {run_url}"]

    lines += ["", "— BeyondTomorrow.World automated pipeline"]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a pipeline completion notification email.")
    parser.add_argument("--to", required=True, help="Recipient email address")
    parser.add_argument("--status", default="failure", help="Job status (success/failure/cancelled)")
    parser.add_argument("--event", default="schedule", help="Trigger event (schedule/workflow_dispatch)")
    parser.add_argument("--topic1", default="", help="First research topic (scheduled runs)")
    parser.add_argument("--topic2", default="", help="Second research topic (scheduled runs)")
    parser.add_argument("--topic3", default="", help="Third research topic (scheduled runs)")
    parser.add_argument("--task", default="", help="Task string for manual dispatch runs")
    parser.add_argument("--run-url", default="", help="GitHub Actions run URL")
    args = parser.parse_args()

    from pipeline.email_listener import send_reply

    topics = [args.topic1, args.topic2, args.topic3]
    subject = _build_subject(args.status, args.event)
    body = _build_body(args.status, args.event, topics, args.task, args.run_url)

    send_reply(args.to, subject, body)
    print(f"Pipeline notification ({args.status}) sent to {args.to}")


if __name__ == "__main__":
    main()
