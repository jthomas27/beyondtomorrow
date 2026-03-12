"""
agents/main.py — CLI entrypoint for the BeyondTomorrow.World research agent

Usage:
    # Run a full blog pipeline
    python -m agents.main "BLOG: quantum computing and cryptography"

    # Run research only (saves to corpus)
    python -m agents.main "RESEARCH: EU AI regulation 2025"

    # Generate a standalone research report
    python -m agents.main "REPORT: impact of rising sea levels on Pacific nations"

    # Index a document from a file
    python -m agents.main "INDEX: path/to/document.txt"

    # Override the model for a run
    python -m agents.main --model gpt-4o-mini "RESEARCH: quick topic"

    # Check status (env vars, db connection, rate limits)
    python -m agents.main status

Options:
    --model MODEL   Override the orchestrator model for this run
                    (e.g. gpt-4o-mini, claude-haiku-3-5, claude-opus-4-6)
    --dry-run       Print what the agent would do without executing LLM calls
    --debug         Enable verbose SDK tracing output

Environment variables required:
    GITHUB_TOKEN      — Fine-grained PAT with models:read scope
    DATABASE_URL      — PostgreSQL connection string (pgvector public TCP proxy)
    GHOST_URL         — Ghost site URL (e.g. https://beyondtomorrow.world)
    GHOST_ADMIN_KEY   — Ghost Admin API key (id:secret format)
"""

from __future__ import annotations

import asyncio
import os
import sys
import argparse
from datetime import datetime


async def _check_status() -> None:
    """Check environment, database connection, and print a status report."""
    print("BeyondTomorrow.World — Agent Status\n" + "=" * 40)

    # Check env vars
    checks = [
        ("GITHUB_TOKEN", "GitHub Models API access"),
        ("DATABASE_URL", "pgvector knowledge corpus"),
        ("GHOST_URL", "Ghost CMS publishing"),
        ("GHOST_ADMIN_KEY", "Ghost Admin API"),
    ]
    all_ok = True
    for var, desc in checks:
        val = os.environ.get(var)
        if val:
            # Show only first 8 chars to confirm it's set without leaking secrets
            preview = val[:8] + "..." if len(val) > 8 else val
            print(f"  ✓ {var:<20} {desc} ({preview})")
        else:
            print(f"  ✗ {var:<20} {desc} — NOT SET")
            all_ok = False

    # Check database connection
    print()
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        try:
            from agents.db import get_pool

            pool = await get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS n FROM embeddings"
                )
            print(f"  ✓ Database connected — {row['n']:,} embeddings in corpus")
        except Exception as exc:
            print(f"  ✗ Database connection failed: {exc}")
            all_ok = False
    else:
        print("  ✗ Database check skipped — DATABASE_URL not set")

    print()
    if all_ok:
        print("Status: READY ✓")
    else:
        print("Status: NOT READY — fix the issues above before running agents")


async def _run_agent(task: str, model_override: str | None = None, debug: bool = False) -> None:
    """Initialise the SDK and run the pipeline agents sequentially."""
    from agents._sdk import Runner
    from agents.setup import init_github_models, ensure_db_schema
    from agents.definitions import researcher, writer, editor, publisher, indexer

    # Initialise GitHub Models API client
    init_github_models()
    await ensure_db_schema()

    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG)

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Starting: {task}")
    print("-" * 60)

    task_upper = task.upper()
    is_blog = "BLOG:" in task_upper

    # Determine today's date prefix for filenames
    date_prefix = datetime.now().strftime("%Y-%m-%d")

    # --- Step 1: Researcher ---
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Running Researcher...")
    research_task = (
        f"{task}\n\n"
        f"Save research as: {date_prefix}-research-<slug>.json"
    )
    researcher_result = await Runner.run(
        researcher.clone(handoffs=[]),
        input=research_task,
        max_turns=20,
    )
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Researcher done.")
    research_filename = _extract_filename(researcher_result.final_output, ".json")
    print(f"  Research file: {research_filename}")

    if not is_blog:
        # RESEARCH / REPORT task: just index the research file
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Running Indexer...")
        index_result = await Runner.run(
            indexer.clone(handoffs=[]),
            input=f"Index this research file into the knowledge corpus: {research_filename}",
            max_turns=10,
        )
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Indexer done.")
        print("-" * 60)
        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Complete")
        print()
        print(f"Research file: research/{research_filename}")
        print(index_result.final_output)
        return

    # --- Step 2: Writer ---
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Running Writer...")
    # Extract feature image URL if present in original task
    feature_image = ""
    if "feature image:" in task.lower() or "feature_image:" in task.lower():
        import re
        m = re.search(r'feature[_ ]image:\s*(https?://\S+)', task, re.IGNORECASE)
        if m:
            feature_image = f"\nFeature image URL: {m.group(1)}"
    writer_result = await Runner.run(
        writer.clone(handoffs=[]),
        input=(
            f"Write a blog post based on the following research.\n"
            f"Research file: {research_filename}\n"
            f"Original task: {task}{feature_image}\n\n"
            f"Read the research file, write the post, and save it as "
            f"{date_prefix}-<slug>.md in the research/ directory."
        ),
        max_turns=10,
    )
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Writer done.")
    draft_filename = _extract_filename(writer_result.final_output, ".md")
    print(f"  Draft file: {draft_filename}")

    # --- Step 3: Editor ---
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Running Editor...")
    editor_result = await Runner.run(
        editor.clone(handoffs=[]),
        input=(
            f"Edit and fact-check this blog post draft.\n"
            f"Draft file: {draft_filename}\n"
            f"Research file (for fact-checking): {research_filename}\n\n"
            f"Save the edited version as {draft_filename.replace('.md', '-edited.md')} "
            f"(append -edited before .md)."
        ),
        max_turns=10,
    )
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Editor done.")
    edited_filename = _extract_filename(editor_result.final_output, ".md")
    if not edited_filename:
        edited_filename = draft_filename.replace(".md", "-edited.md")
    print(f"  Edited file: {edited_filename}")

    # --- Step 4: Publisher ---
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Running Publisher...")
    publisher_result = await Runner.run(
        publisher.clone(handoffs=[]),
        input=(
            f"Publish this blog post to Ghost CMS as a draft.\n"
            f"Post file: {edited_filename}\n"
            f"Read the file, extract the frontmatter (title, tags, excerpt, feature_image), "
            f"and publish to Ghost with status='draft'."
        ),
        max_turns=10,
    )
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Publisher done.")
    ghost_output = publisher_result.final_output

    # --- Step 5: Indexer ---
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Running Indexer...")
    index_result = await Runner.run(
        indexer.clone(handoffs=[]),
        input=f"Index this research file into the knowledge corpus: {research_filename}",
        max_turns=10,
    )
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Indexer done.")

    print("-" * 60)
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Complete")
    print()
    print(ghost_output)
    print(index_result.final_output)


def _extract_filename(text: str, ext: str) -> str:
    """Extract the first filename with the given extension from agent output text."""
    import re
    # Match bare filenames like 2026-03-12-something.json or research/2026-03-12-something.json
    pattern = rf'[\w/.\-]+{re.escape(ext)}'
    matches = re.findall(pattern, text)
    for m in matches:
        # Strip leading research/ prefix since tools expect just the filename
        name = m.lstrip("/")
        if name.startswith("research/"):
            name = name[len("research/"):]
        if ext in name:
            return name
    return ""


def main() -> None:
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
        help="Override the orchestrator model (e.g. claude-haiku-3-5)",
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

    asyncio.run(_run_agent(args.task, model_override=args.model, debug=args.debug))


if __name__ == "__main__":
    main()
