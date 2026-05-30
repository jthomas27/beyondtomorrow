#!/usr/bin/env python3
"""scripts/notify_research_failure.py

Sends a failure notification email via Hostinger SMTP.
Called by the GitHub Actions workflow when the research job fails.

Required env vars (set as GitHub Actions secrets):
    SMTP_USER   — sender address (e.g. admin@beyondtomorrow.world)
    SMTP_PASS   — Hostinger email password

Usage:
    python scripts/notify_research_failure.py \\
        --to admin@beyondtomorrow.world \\
        --topic "Weekly research run" \\
        --error "One or more steps failed" \\
        --run-url "https://github.com/owner/repo/actions/runs/12345"
"""

import argparse
import sys
from pathlib import Path

# Add project root so pipeline imports resolve correctly
sys.path.insert(0, str(Path(__file__).parent.parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a research failure notification email.")
    parser.add_argument("--to", required=True, help="Recipient email address")
    parser.add_argument("--topic", required=True, help="Job description or topic that failed")
    parser.add_argument("--error", default="Unknown error", help="Error summary")
    parser.add_argument("--run-url", default="", help="GitHub Actions run URL")
    args = parser.parse_args()

    from pipeline.email_listener import send_reply

    subject = "[BeyondTomorrow] Research job failed"
    body_lines = [
        "The automated weekly research job failed on GitHub Actions.",
        "",
        f"Job:   {args.topic}",
        f"Error: {args.error}",
    ]
    if args.run_url:
        body_lines += ["", f"View run: {args.run_url}"]
    body_lines += [
        "",
        "Check the Actions log for full details.",
        "— BeyondTomorrow.World automated pipeline",
    ]

    send_reply(args.to, subject, "\n".join(body_lines))
    print(f"Failure notification sent to {args.to}")


if __name__ == "__main__":
    main()
