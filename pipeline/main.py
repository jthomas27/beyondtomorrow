"""pipeline/main.py — CLI entrypoint for the BeyondTomorrow.World research agent

Usage:
    # Run a full blog pipeline
    python -m pipeline.main "BLOG: quantum computing and cryptography"

    # Run research only (saves to corpus)
    python -m pipeline.main "RESEARCH: EU AI regulation 2025"

    # Generate a standalone research report
    python -m pipeline.main "REPORT: impact of rising sea levels on Pacific nations"

    # Index a document from a file
    python -m pipeline.main "INDEX: path/to/document.txt"

    # Override the model for a run
    python -m pipeline.main --model gpt-6-luna "Summarise this topic"

    # Check status (env vars, db connection, rate limits)
    python -m pipeline.main status

Options:
    --model MODEL   Override the orchestrator model for this run
                    (e.g. gpt-6.1-sol, gpt-6-luna)
    --dry-run       Print what the agent would do without executing LLM calls
    --debug         Enable verbose SDK tracing output

Environment variables required:
    OPENAI_API_KEY    — OpenAI platform API key (sk-...)
    DATABASE_URL      — PostgreSQL connection string (pgvector public TCP proxy)
    GHOST_URL         — Ghost site URL (e.g. https://beyondtomorrow.world)
    GHOST_ADMIN_KEY   — Ghost Admin API key (id:secret format)"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from pipeline.paths import PROJECT_ROOT

from pipeline.settings import load_environment as _load_dotenv


_load_dotenv()

from pipeline.workflows.notifications import _send_pipeline_notification, _fmt_pipeline_stages  # compatibility exports
from pipeline.workflows.execution import _is_rate_limit_error, _is_413_error, _extract_usage, _run_agent_with_fallback, _fix_title_via_llm  # compatibility exports
from pipeline.workflows.evidence import _valid_research_cache, _require_research_evidence, _require_publish_evidence, _compact_research, _sanitise_research_sources  # compatibility exports
from pipeline.workflows.publishing import _build_publish_input, _parse_publish_output, _linkedin_post_direct  # compatibility exports
from pipeline.workflows.blog import _run_blog_pipeline  # compatibility exports
from pipeline.workflows.publish import _run_publish_only  # compatibility exports
from pipeline.workflows.research import _run_research_pipeline  # compatibility exports
from pipeline.workflows.index import _run_index  # compatibility exports
from pipeline.workflows.agent import _run_agent  # compatibility exports
from pipeline.workflows.status import _check_status  # compatibility exports


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="BeyondTomorrow.World research agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "task",
        nargs="?",
        help="Task to run. Prefix with BLOG:, RESEARCH:, REPORT:, or INDEX:",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override the orchestrator model for unprefixed tasks (e.g. gpt-6-luna)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without executing LLM calls",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose SDK tracing output",
    )

    args = parser.parse_args()

    if args.task == "status" or args.task is None and len(sys.argv) == 1:
        asyncio.run(_check_status())
        return

    if args.task is None:
        parser.print_help()
        sys.exit(1)

    if args.dry_run:
        print(f"[dry-run] Would execute: {args.task}")
        if args.model:
            print(f"[dry-run] Model override: {args.model}")
        return

    task_upper = args.task.upper()
    if task_upper.startswith("BLOG:"):
        asyncio.run(_run_blog_pipeline(args.task, debug=args.debug))
    elif task_upper.startswith("PUBLISH:"):
        asyncio.run(_run_publish_only(args.task, debug=args.debug))
    elif task_upper.startswith(("RESEARCH:", "REPORT:")):
        asyncio.run(_run_research_pipeline(args.task, debug=args.debug))
    elif task_upper.startswith("INDEX:"):
        asyncio.run(_run_index(args.task))
    else:
        asyncio.run(_run_agent(args.task, model_override=args.model, debug=args.debug))


if __name__ == "__main__":
    main()
