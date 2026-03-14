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
    python -m agents.main --model openai/gpt-5-mini "RESEARCH: quick topic"

    # Check status (env vars, db connection, rate limits)
    python -m agents.main status

Options:
    --model MODEL   Override the orchestrator model for this run
                    (e.g. openai/gpt-5-mini, openai/gpt-5-nano, openai/gpt-4.1)
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
import logging
import os
import sys
import argparse
from datetime import datetime

logger = logging.getLogger("pipeline")

# Default timeout per agent step (seconds)
_AGENT_TIMEOUT = 300


def _compact_research(research_output: str, max_chars: int = 1500) -> str:
    """Return a token-budget-friendly summary of the research JSON.

    Extracts the fields the writer/editor actually need (key_findings,
    suggested_angles, subtopics, source_list) and drops bulk like full
    summaries and redundant metadata.  Falls back to a plain truncation
    if the output is not valid JSON.
    """
    import json as _json

    try:
        data = _json.loads(research_output)
    except Exception:
        # Not JSON — just truncate with a note
        return research_output[:max_chars] + ("\n[truncated]" if len(research_output) > max_chars else "")

    parts: list[str] = []

    # Key findings — keep finding text, confidence, and sources
    findings = data.get("key_findings", [])
    if findings:
        parts.append("KEY FINDINGS:")
        for f in findings:
            src = ", ".join(f.get("sources", [])[:2])
            conf = f.get("confidence", "unknown")
            parts.append(f"- {f.get('finding', '')} [{conf}] ({src})")

    # Suggested angles
    angles = data.get("suggested_angles", [])
    if angles:
        parts.append("\nSUGGESTED ANGLES:")
        for a in angles:
            parts.append(f"- {a}")

    # Subtopics — name + bullet points only, skip full summaries
    subtopics = data.get("subtopics", [])
    if subtopics:
        parts.append("\nSUBTOPICS:")
        for s in subtopics:
            parts.append(f"  {s.get('name', '')}:")
            for bp in s.get("bullet_points", []):
                parts.append(f"    • {bp}")

    # Source list — url + title only
    sources = data.get("source_list", [])
    if sources:
        parts.append("\nSOURCES:")
        for src in sources:
            parts.append(f"- {src.get('title', 'Untitled')}: {src.get('url', '')}")

    compact = "\n".join(parts)
    if len(compact) > max_chars:
        compact = compact[:max_chars] + "\n[truncated]"
    return compact


def _load_dotenv() -> None:
    """Load .env from the project root if it exists (no dotenv package needed)."""
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if not os.path.isfile(env_path):
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and value and key not in os.environ:
                os.environ[key] = value


_load_dotenv()


async def _check_status() -> None:
    """Check environment, database connection, and print a status report."""
    logger.info("BeyondTomorrow.World — Agent Status")
    logger.info("=" * 40)

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
            preview = val[:8] + "..." if len(val) > 8 else val
            logger.info("  ✓ %s %s (%s)", f"{var:<20}", desc, preview)
        else:
            logger.error("  ✗ %s %s — NOT SET", f"{var:<20}", desc)
            all_ok = False

    # Check database connection
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        try:
            from pipeline.db import get_pool

            pool = await get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT COUNT(*) AS n FROM embeddings"
                )
            logger.info("  ✓ Database connected — %s embeddings in corpus", f"{row['n']:,}")
        except Exception as exc:
            logger.error("  ✗ Database connection failed: %s", exc)
            all_ok = False
    else:
        logger.error("  ✗ Database check skipped — DATABASE_URL not set")

    if all_ok:
        logger.info("Status: READY ✓")
    else:
        logger.error("Status: NOT READY — fix the issues above before running agents")


async def _run_blog_pipeline(task: str, debug: bool = False) -> None:
    """Run the full BLOG pipeline: Research+Index → Write → Edit → Publish → Index."""
    from pathlib import Path

    from pipeline._sdk import Runner
    from pipeline.setup import init_github_models
    from pipeline.definitions import researcher, writer, editor, publisher, indexer
    from pipeline.db import get_pool, close_pool
    from pipeline.degradation import select_model
    from pipeline.guardrails import log_model_call

    init_github_models()

    # Disable tracing — GitHub token is not a valid OpenAI key
    import os as _os
    _os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"

    topic = task.partition(":")[2].strip() if ":" in task else task
    research_dir = Path(__file__).parent.parent / "research"
    research_dir.mkdir(exist_ok=True)

    today_str = datetime.now().strftime("%Y-%m-%d")
    slug = "-".join(topic.lower().split()[:4]).replace(",", "").replace("'", "")
    draft_filename = f"{today_str}-{slug}.md"
    edited_filename = f"{today_str}-{slug}-edited.md"

    logger.info("Starting BLOG pipeline")
    logger.info("Topic: %s", topic)

    try:
        pool = await get_pool()

        # --- Step 1: Research ---
        logger.info("[1/5] Researching and indexing sources to DB...")

        # Skip research if the draft already exists (e.g. pipeline resumed after failure)
        if (research_dir / draft_filename).exists() or (research_dir / edited_filename).exists():
            logger.info("Draft already exists — skipping research step.")
            research_output = "{}"
        else:
            from openai import RateLimitError
            from pipeline.degradation import get_fallback

            research_input = (
                f"Research this topic thoroughly for a blog post: {topic}\n\n"
                f"REQUIRED STEPS:\n"
                f"1. Generate 3-5 search queries covering different angles.\n"
                f"2. For each query call search_and_index — this fetches full pages and "
                f"stores text + embeddings directly in the knowledge database (not temp files).\n"
                f"3. Call search_corpus after indexing to retrieve the stored knowledge.\n"
                f"4. Call search_arxiv for scientific papers on this topic.\n"
                f"5. Return structured research JSON with key_findings, subtopics, "
                f"suggested_angles, gaps, source_list, total_sources, model_used."
            )

            research_model = await select_model(researcher.model, pool=pool)
            research_output = None
            for _attempt in range(3):
                if research_model != researcher.model:
                    logger.warning("Researcher degraded: %s → %s", researcher.model, research_model)
                researcher.model = research_model
                try:
                    research_result = await asyncio.wait_for(
                        Runner.run(researcher, max_turns=15, input=research_input),
                        timeout=_AGENT_TIMEOUT,
                    )
                    research_output = research_result.final_output
                    break
                except RateLimitError:
                    fallback = get_fallback(research_model)
                    if fallback:
                        logger.warning("Rate limited on %s — falling back to %s", research_model, fallback)
                        research_model = fallback
                    else:
                        raise

            if research_output is None:
                raise RuntimeError("Research step failed after all retries")
            await log_model_call(pool, research_model, phase="research")
            logger.info("Research complete")

        research_doc_name = f"{today_str}-{slug}-research"
        try:
            from pipeline.tools.corpus import index_document
            await index_document(
                content=research_output,
                source=research_doc_name,
                doc_type="research",
            )
            logger.info("Research JSON saved to DB as '%s'", research_doc_name)
        except Exception as _idx_err:
            logger.warning("Could not save research to DB: %s", _idx_err)

        # --- Step 2: Write draft ---
        logger.info("[2/5] Writing draft...")
        research_compact = _compact_research(research_output)

        writer_model = await select_model(writer.model, pool=pool)
        if writer_model != writer.model:
            logger.warning("Writer degraded: %s → %s", writer.model, writer_model)
            writer.model = writer_model

        if (research_dir / draft_filename).exists():
            write_output = f"(skipped — draft already exists: {draft_filename})"
            logger.info("Draft already exists, skipping writer: %s", draft_filename)
        else:
            existing_drafts = set(research_dir.glob("*.md"))

            async def _run_writer(extra_prefix: str = "") -> str:
                result = await asyncio.wait_for(
                    Runner.run(
                        writer,
                        max_turns=10,
                        input=(
                            f"{extra_prefix}"
                            f"Write a blog post about: {topic}\n"
                            f"You MUST call write_research_file with filename '{draft_filename}' "
                            f"to save the post before you finish — do not stop without saving.\n\n"
                            f"Research findings:\n{research_compact}"
                        ),
                    ),
                    timeout=_AGENT_TIMEOUT,
                )
                return result.final_output

            write_output = await _run_writer()
            await log_model_call(pool, writer_model, phase="writer")
            new_drafts = [
                f for f in research_dir.glob("*.md")
                if f not in existing_drafts and "-edited" not in f.name
            ]
            if not new_drafts:
                logger.warning("Writer did not save a file — retrying with explicit instruction...")
                write_output = await _run_writer(
                    f"CRITICAL: You MUST call write_research_file('{draft_filename}', ...) "
                    f"as your very first action. Do not respond without saving the file first.\n\n"
                )
                await log_model_call(pool, writer_model, phase="writer-retry")
                new_drafts = [
                    f for f in research_dir.glob("*.md")
                    if f not in existing_drafts and "-edited" not in f.name
                ]

            if new_drafts:
                draft_filename = max(new_drafts, key=lambda f: f.stat().st_mtime).name

        logger.info("Draft saved: %s", draft_filename)

        # --- Step 3: Edit ---
        logger.info("[3/5] Editing...")
        editor_model = await select_model(editor.model, pool=pool)
        if editor_model != editor.model:
            logger.warning("Editor degraded: %s → %s", editor.model, editor_model)
            editor.model = editor_model

        if (research_dir / edited_filename).exists():
            logger.info("Edited file already exists, skipping editor: %s", edited_filename)
        else:
            try:
                await asyncio.wait_for(
                    Runner.run(
                        editor,
                        max_turns=10,
                        input=(
                            f"Edit the blog post draft.\n"
                            f"1. Call read_research_file('{draft_filename}') to read the draft.\n"
                            f"2. Save your edits as '{edited_filename}' using write_research_file.\n\n"
                            f"Research JSON filename for fact-checking: {today_str}-{slug}-research\n"
                            f"(Call read_research_file with that name if you need to verify claims.)"
                        ),
                    ),
                    timeout=_AGENT_TIMEOUT,
                )
                await log_model_call(pool, editor_model, phase="editor")
            except asyncio.TimeoutError:
                logger.error("Editor timed out after %ds", _AGENT_TIMEOUT)
                if (research_dir / edited_filename).exists():
                    logger.warning("Editor timed out but saved file — proceeding.")
                else:
                    logger.warning("Editor timed out without saving. Using original draft.")
                    edited_filename = draft_filename
            except Exception as _edit_err:
                _is_token_err = "413" in str(_edit_err) or "tokens_limit_reached" in str(_edit_err)
                _is_rate_err = "429" in str(_edit_err) or "RateLimitError" in type(_edit_err).__name__ or "Too many requests" in str(_edit_err)
                if (_is_token_err or _is_rate_err) and (research_dir / edited_filename).exists():
                    logger.warning("Editor hit API limit after saving — proceeding with saved file.")
                elif _is_token_err or _is_rate_err:
                    logger.warning("Editor hit API limit, file not saved. Using original draft.")
                    edited_filename = draft_filename
                else:
                    raise
            else:
                if not (research_dir / edited_filename).exists():
                    logger.warning("Editor did not save '%s'. Using original draft.", edited_filename)
                    edited_filename = draft_filename
        logger.info("Edit complete: %s", edited_filename)

        # --- Step 4: Publish ---
        logger.info("[4/5] Publishing to Ghost...")
        publish_result = await asyncio.wait_for(
            Runner.run(
                publisher,
                max_turns=6,
                input=(
                    f"Publish the blog post file '{edited_filename}' to Ghost.\n"
                    f"Step 1: call pick_random_asset_image()\n"
                    f"Step 2: call upload_image_to_ghost(image_path=<path from step 1>)\n"
                    f"Step 3: call publish_file_to_ghost(filename='{edited_filename}', feature_image_url=<url from step 2>, status='published')\n"
                    f"Return only the published URL from step 3."
                ),
            ),
            timeout=_AGENT_TIMEOUT,
        )
        await log_model_call(pool, publisher.model, phase="publisher")
        publish_output = publish_result.final_output

        # --- Handle MISSING: validation failures from publish_file_to_ghost ---
        if publish_output.strip().startswith("MISSING:"):
            logger.warning("Publish blocked — pre-publish validation failed: %s", publish_output)
            missing_lower = publish_output.lower()

            if "title" in missing_lower or "body_content" in missing_lower or "just for laughs" in missing_lower or "source links" in missing_lower or "excerpt" in missing_lower:
                logger.info("Recovering: re-running Editor to fix content issues...")
                await asyncio.wait_for(
                    Runner.run(
                        editor,
                        max_turns=10,
                        input=(
                            f"The blog post FAILED pre-publish validation with this error:\n"
                            f"{publish_output}\n\n"
                            f"Fix ALL reported issues before saving:\n"
                            f"- If 'title' issue: rewrite to be 5–10 words, factual, punchy.\n"
                            f"- If 'body_content' too short: expand to at least 1500 words.\n"
                            f"- If 'Just For Laughs' missing: add a ## Just For Laughs section with a topic-related joke.\n"
                            f"- If 'source links' missing: add inline markdown links to sources.\n"
                            f"- If 'excerpt' missing: add a 1–2 sentence excerpt in frontmatter.\n\n"
                            f"1. Call read_research_file('{draft_filename}') to read the original draft.\n"
                            f"2. Fix every reported validation issue.\n"
                            f"3. Save the corrected post as '{edited_filename}' using write_research_file."
                        ),
                    ),
                    timeout=_AGENT_TIMEOUT,
                )
                await log_model_call(pool, editor_model, phase="editor-recovery")

            logger.info("Retrying Publisher after recovery...")
            publish_result = await asyncio.wait_for(
                Runner.run(
                    publisher,
                    max_turns=6,
                    input=(
                        f"Publish the blog post file '{edited_filename}' to Ghost.\n"
                        f"Step 1: call pick_random_asset_image()\n"
                        f"Step 2: call upload_image_to_ghost(image_path=<path from step 1>)\n"
                        f"Step 3: call publish_file_to_ghost(filename='{edited_filename}', "
                        f"feature_image_url=<url from step 2>, status='published')\n"
                        f"Return only the published URL from step 3."
                    ),
                ),
                timeout=_AGENT_TIMEOUT,
            )
            await log_model_call(pool, publisher.model, phase="publisher-retry")
            publish_output = publish_result.final_output
            if publish_output.strip().startswith("MISSING:"):
                raise RuntimeError(
                    f"Pipeline aborted — publish validation still failing after recovery attempt.\n"
                    f"Unresolved: {publish_output}"
                )

        logger.info("Published: %s", publish_output)

        # --- Step 5: Index research to corpus ---
        logger.info("[5/5] Indexing edited post to corpus...")
        index_result = await asyncio.wait_for(
            Runner.run(
                indexer,
                max_turns=8,
                input=(
                    f"Index the edited blog post into the corpus as an 'article' document.\n"
                    f"1. Call read_research_file('{edited_filename}') to read the post.\n"
                    f"2. Call index_document with source='{today_str}-{slug}', doc_type='article'.\n"
                    f"Published post URL: {publish_output}"
                ),
            ),
            timeout=_AGENT_TIMEOUT,
        )
        await log_model_call(pool, indexer.model, phase="indexer")
        index_output = index_result.final_output

        logger.info("BLOG pipeline complete")
        logger.info("Published: %s", publish_output)
        logger.info("Corpus: %s", index_output)
    finally:
        await close_pool()


async def _run_publish_only(task: str, debug: bool = False) -> None:
    """Run only the Publisher step for an already-edited file.

    Usage:  python -m pipeline.main "PUBLISH: 2026-03-13-my-post-edited.md"
    """
    from pipeline._sdk import Runner
    from pipeline.setup import init_github_models
    from pipeline.definitions import publisher
    from pipeline.db import close_pool

    init_github_models()

    filename = task.partition(":")[2].strip()
    logger.info("Publishing '%s'...", filename)

    try:
        publish_result = await asyncio.wait_for(
            Runner.run(
                publisher,
                max_turns=6,
                input=(
                    f"Publish the blog post file '{filename}' to Ghost.\n"
                    f"Step 1: call pick_random_asset_image()\n"
                    f"Step 2: call upload_image_to_ghost(image_path=<path from step 1>)\n"
                    f"Step 3: call publish_file_to_ghost(filename='{filename}', feature_image_url=<url from step 2>, status='published')\n"
                    f"Return only the published URL from step 3."
                ),
            ),
            timeout=_AGENT_TIMEOUT,
        )
        logger.info("Result: %s", publish_result.final_output)
    finally:
        await close_pool()


async def _run_research_pipeline(task: str, debug: bool = False) -> None:
    """Run RESEARCH or REPORT: Research + Index, no blog post."""
    from pipeline._sdk import Runner
    from pipeline.setup import init_github_models
    from pipeline.definitions import researcher, indexer
    from pipeline.db import get_pool, close_pool
    from pipeline.degradation import select_model
    from pipeline.guardrails import log_model_call

    init_github_models()

    prefix, _, topic = task.partition(":")
    topic = topic.strip()
    today_str = datetime.now().strftime("%Y-%m-%d")
    slug = "-".join(topic.lower().split()[:4]).replace(",", "").replace("'", "")

    logger.info("Starting %s pipeline", prefix.strip().upper())
    logger.info("Topic: %s", topic)

    try:
        pool = await get_pool()

        research_model = await select_model(researcher.model, pool=pool)
        if research_model != researcher.model:
            logger.warning("Researcher degraded: %s → %s", researcher.model, research_model)
            researcher.model = research_model

        research_result = await asyncio.wait_for(
            Runner.run(
                researcher,
                max_turns=15,
                input=(
                    f"Research this topic thoroughly: {topic}\n\n"
                    f"REQUIRED STEPS:\n"
                    f"1. Generate 3-5 search queries covering different angles.\n"
                    f"2. For each query call search_and_index.\n"
                    f"3. Call search_corpus after indexing.\n"
                    f"4. Call search_arxiv for scientific papers.\n"
                    f"5. Return structured research JSON."
                ),
            ),
            timeout=_AGENT_TIMEOUT,
        )
        await log_model_call(pool, research_model, phase="research")
        logger.info("Research complete")

        # Index to corpus
        logger.info("Indexing research to corpus...")
        index_result = await asyncio.wait_for(
            Runner.run(
                indexer,
                max_turns=8,
                input=(
                    f"Index this research output into the corpus.\n"
                    f"Content:\n{research_result.final_output}\n\n"
                    f"Source name: '{today_str}-{slug}-research'\n"
                    f"doc_type: 'research'"
                ),
            ),
            timeout=_AGENT_TIMEOUT,
        )
        await log_model_call(pool, indexer.model, phase="indexer")

        logger.info("%s pipeline complete", prefix.strip().upper())
        logger.info("Corpus: %s", index_result.final_output)
    finally:
        await close_pool()


async def _run_agent(task: str, model_override: str | None = None, debug: bool = False) -> None:
    """Initialise the SDK and run the orchestrator with the given task."""
    from pipeline._sdk import Runner
    from pipeline.setup import init_github_models
    from pipeline.definitions import orchestrator
    from pipeline.db import close_pool

    init_github_models()

    if model_override:
        from pipeline._sdk import ModelSettings
        orchestrator.model = model_override

    if debug:
        import sys as _sys
        _sdk_path = next(
            (p for p in _sys.path if "site-packages" in p and p != ""), None
        )
        if _sdk_path:
            _sys.path.insert(0, _sdk_path)
        try:
            from agents.tracing import set_tracing_export_api_enabled
            set_tracing_export_api_enabled(False)
        except ImportError:
            pass
        finally:
            if _sdk_path and _sys.path[0] == _sdk_path and "site-packages" in _sys.path[0]:
                _sys.path.pop(0)

    logger.info("Starting: %s", task)

    try:
        result = await asyncio.wait_for(
            Runner.run(orchestrator, input=task, max_turns=30),
            timeout=_AGENT_TIMEOUT * 3,  # orchestrator may run multiple agents
        )
        logger.info("Complete")
        print(result.final_output)
    finally:
        await close_pool()


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

    task_upper = args.task.upper()
    if task_upper.startswith("BLOG:"):
        asyncio.run(_run_blog_pipeline(args.task, debug=args.debug))
    elif task_upper.startswith("PUBLISH:"):
        asyncio.run(_run_publish_only(args.task, debug=args.debug))
    elif task_upper.startswith(("RESEARCH:", "REPORT:")):
        asyncio.run(_run_research_pipeline(args.task, debug=args.debug))
    else:
        asyncio.run(_run_agent(args.task, model_override=args.model, debug=args.debug))


if __name__ == "__main__":
    main()
