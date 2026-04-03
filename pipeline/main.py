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
    python -m agents.main --model openai/gpt-4.1-mini "RESEARCH: quick topic"

    # Check status (env vars, db connection, rate limits)
    python -m agents.main status

Options:
    --model MODEL   Override the orchestrator model for this run
                    (e.g. openai/gpt-4.1, openai/gpt-4.1-mini, openai/gpt-4.1-nano)
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
from time import monotonic

logger = logging.getLogger("pipeline")

# Default timeout per agent step (seconds)
_AGENT_TIMEOUT = 300

# Cooldown between pipeline stages (seconds).
# With RPM-aware guardrails, a short cooldown suffices.
_STAGE_COOLDOWN = 20
_RETRY_BACKOFF_BASE = 20  # seconds; exponential: 20, 40, 80, 160, …


# ---------------------------------------------------------------------------
# Shared rate-limit / model-limit error detection
# ---------------------------------------------------------------------------

def _is_rate_limit_error(exc: Exception) -> bool:
    """Return True for errors that warrant falling back to a different model.

    Covers: 429 RateLimitError, 413 body-too-large, 400 unsupported-param.
    """
    from openai import RateLimitError, APIStatusError, BadRequestError

    if isinstance(exc, RateLimitError):
        return True
    if isinstance(exc, BadRequestError):
        msg = str(exc).lower()
        if "unsupported parameter" in msg or "unsupported value" in msg:
            return True
        # Azure content filter false positives — retry with fallback model
        if "content_filter" in msg or "content management policy" in msg:
            return True
        return False
    if isinstance(exc, APIStatusError) and exc.status_code in (413, 429):
        return True
    msg = str(exc)
    return "tokens_limit_reached" in msg or "Request body too large" in msg


# ---------------------------------------------------------------------------
# Unified agent runner with retry + model fallback + exponential backoff
# ---------------------------------------------------------------------------

def _extract_usage(result) -> tuple[int, int]:
    """Extract total (input_tokens, output_tokens) from a RunResult."""
    tokens_in = tokens_out = 0
    for resp in getattr(result, "raw_responses", []):
        usage = getattr(resp, "usage", None)
        if usage:
            tokens_in += getattr(usage, "input_tokens", 0) or 0
            tokens_out += getattr(usage, "output_tokens", 0) or 0
    return tokens_in, tokens_out


async def _run_agent_with_fallback(
    agent,
    input_text: str,
    *,
    agent_name: str,
    pool,
    max_turns: int = 10,
    max_attempts: int = 6,
    run_log=None,
) -> tuple[str, int, int]:
    """Run an agent with proactive model selection and automatic fallback.

    Before the first attempt, checks RPM/budget via ``select_model()`` to
    pick the best available model and avoid a wasted 429.

    On each rate-limit/model-limit failure:
    1. Falls back to the next model in the degradation chain.
    2. Waits with exponential backoff (20s, 40s, 60s, …) before retrying.
    3. Re-creates the agent's model_settings to match the new model.

    Raises RuntimeError if all attempts are exhausted.
    Returns ``(final_output, tokens_in, tokens_out)``.
    """
    from pipeline._sdk import Runner
    from pipeline.definitions import model_settings_for
    from pipeline.degradation import get_fallback, select_model

    # Snapshot original model so we can restore it after this call
    original_model = agent.model
    original_settings = agent.model_settings
    current_model = agent.model

    # --- Fix #1: Proactive model selection via budget/RPM checks ---
    try:
        selected = await select_model(current_model, pool=pool)
        if selected != current_model:
            logger.info(
                "%s: proactive switch %s → %s (budget/RPM pressure)",
                agent_name, current_model, selected,
            )
            if run_log:
                run_log.model_fallback(
                    stage=agent_name, agent_name=agent_name,
                    from_model=current_model, to_model=selected,
                    attempt=0, reason="proactive RPM/budget switch",
                )
            current_model = selected
            agent.model = current_model
            agent.model_settings = model_settings_for(
                agent_name.lower(), model_override=current_model
            )
    except Exception as sel_err:
        logger.warning("%s: select_model failed (non-fatal): %s", agent_name, sel_err)

    try:
        for attempt in range(max_attempts):
            try:
                result = await asyncio.wait_for(
                    Runner.run(agent, max_turns=max_turns, input=input_text),
                    timeout=_AGENT_TIMEOUT,
                )
                tokens_in, tokens_out = _extract_usage(result)
                return result.final_output, tokens_in, tokens_out
            except asyncio.TimeoutError:
                logger.error("%s timed out after %ds (attempt %d/%d)",
                             agent_name, _AGENT_TIMEOUT, attempt + 1, max_attempts)
                raise
            except Exception as exc:
                if _is_rate_limit_error(exc):
                    fallback = get_fallback(current_model)
                    if fallback:
                        backoff = min(_RETRY_BACKOFF_BASE * (2 ** attempt), 300)
                        logger.warning(
                            "%s hit rate limit on %s (%s) — falling back to %s "
                            "(waiting %ds, attempt %d/%d)",
                            agent_name, current_model, type(exc).__name__,
                            fallback, backoff, attempt + 1, max_attempts,
                        )
                        if run_log:
                            run_log.model_fallback(
                                stage=agent_name, agent_name=agent_name,
                                from_model=current_model, to_model=fallback,
                                attempt=attempt + 1,
                                reason=f"{type(exc).__name__}: {exc}",
                            )
                        current_model = fallback
                        agent.model = current_model
                        agent.model_settings = model_settings_for(
                            agent_name.lower(), model_override=current_model
                        )
                        await asyncio.sleep(backoff)
                    else:
                        logger.error(
                            "%s exhausted all fallback models after %s on %s",
                            agent_name, type(exc).__name__, current_model,
                        )
                        raise RuntimeError(
                            f"{agent_name} failed — rate-limited on every model in "
                            f"the fallback chain. Last model: {current_model}"
                        ) from exc
                else:
                    raise

        raise RuntimeError(f"{agent_name} failed after {max_attempts} attempts")
    finally:
        # Always restore original model so fallback doesn't leak to next stage
        agent.model = original_model
        agent.model_settings = original_settings


def _compact_research(research_output: str, max_chars: int = 3000) -> str:
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

    def _is_external_url(url: str) -> bool:
        """Return True only for http/https URLs (not file paths or corpus refs)."""
        return isinstance(url, str) and url.startswith(("http://", "https://"))

    # Key findings — keep finding text, confidence, and external sources only
    findings = data.get("key_findings", [])
    if findings:
        parts.append("KEY FINDINGS:")
        for f in findings:
            ext_sources = [s for s in f.get("sources", []) if _is_external_url(s)]
            src = ", ".join(ext_sources[:2])
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

    # Source list — external URLs only (no corpus refs or file paths)
    sources = data.get("source_list", [])
    ext_sources = [s for s in sources if _is_external_url(s.get("url", ""))]
    if ext_sources:
        parts.append("\nSOURCES (external links only — use these for inline citations):")
        for src in ext_sources:
            parts.append(f"- {src.get('title', 'Untitled')}: {src.get('url', '')}")

    compact = "\n".join(parts)
    if len(compact) > max_chars:
        truncated = compact[:max_chars].rsplit("\n", 1)[0]
        compact = truncated + "\n[... truncated — use search_corpus for additional sources]"
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


# ---------------------------------------------------------------------------
# Shared publish input builder — avoids duplication between _run_blog_pipeline
# and _run_publish_only.
# ---------------------------------------------------------------------------

def _build_publish_input(filename: str) -> str:
    """Build the Publisher agent prompt for a given edited markdown filename."""
    return (
        f"Publish the blog post file '{filename}' to Ghost, then cross-post to LinkedIn.\n"
        f"Step 1: call pick_random_asset_image()\n"
        f"Step 2: call upload_image_to_ghost(image_path=<path from step 1>)\n"
        f"Step 3: call publish_file_to_ghost(filename='{filename}', "
        f"feature_image_url=<url from step 2>, status='published')\n"
        f"Step 4: call post_to_linkedin(title=<title from frontmatter>, "
        f"excerpt=<excerpt from frontmatter>, post_url=<ghost url from step 3>, "
        f"tags=<tags from frontmatter>, feature_image_url=<url from step 2>). "
        f"If result starts with 'SKIPPED:' or 'Error:', log it and continue.\n"
        f"Return the Ghost URL from step 3 and the LinkedIn result from step 4."
    )


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

    # LinkedIn cross-posting (optional — non-blocking)
    from datetime import date as _date
    li_token = os.environ.get("LINKEDIN_ACCESS_TOKEN", "").strip()
    li_urn = os.environ.get("LINKEDIN_PERSON_URN", "").strip()
    li_expires = os.environ.get("LINKEDIN_TOKEN_EXPIRES", "").strip()
    if li_token and li_urn:
        expiry_info = ""
        if li_expires:
            try:
                days_left = (_date.fromisoformat(li_expires) - _date.today()).days
                if days_left <= 0:
                    expiry_info = f" ⚠️  TOKEN EXPIRED on {li_expires} — re-run scripts/linkedin_auth.py"
                elif days_left <= 7:
                    expiry_info = f" ⚠️  expires in {days_left}d on {li_expires} — refresh soon"
                else:
                    expiry_info = f" (expires {li_expires}, {days_left}d remaining)"
            except ValueError:
                expiry_info = f" (LINKEDIN_TOKEN_EXPIRES invalid: {li_expires!r})"
        else:
            expiry_info = " (expiry unknown — re-run scripts/linkedin_auth.py to set LINKEDIN_TOKEN_EXPIRES)"
        logger.info("  ✓ %-20s LinkedIn cross-posting%s", "LINKEDIN_ACCESS_TOKEN", expiry_info)
        li_company = os.environ.get("LINKEDIN_COMPANY_URN", "").strip()
        if li_company:
            logger.info("  ✓ %-20s LinkedIn company page (%s)", "LINKEDIN_COMPANY_URN", li_company)
        else:
            logger.info(
                "  - %-20s LinkedIn company page not configured "
                "(set LINKEDIN_COMPANY_URN to also post to the Beyond Tomorrow page)",
                "LINKEDIN_COMPANY_URN",
            )
    else:
        logger.info("  - %-20s LinkedIn not configured (optional — pipeline will skip cross-posting)", "LINKEDIN")

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


async def _run_blog_pipeline(task: str, debug: bool = False) -> dict:
    """Run the full BLOG pipeline: Research+Index → Write → Edit → Publish → Index."""
    from pathlib import Path

    from pipeline._sdk import Runner
    from pipeline.setup import init_github_models
    from pipeline.definitions import researcher, writer, editor, publisher, indexer, model_settings_for
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

    from pipeline.pipeline_logger import PipelineRunLogger
    run_log = PipelineRunLogger(topic=topic, command="BLOG")
    _current_stage = "init"
    _pipeline_t0 = monotonic()
    _pipeline_result: dict = {
        "status": "failed", "published_url": "", "run_log": run_log, "total_elapsed_s": 0.0
    }

    try:
        pool = await get_pool()
        _pipeline_t0 = monotonic()

        # =============================================================
        # Step 1: Research
        # =============================================================
        _current_stage = "Research"
        run_log.stage_start("Research")
        logger.info("[1/5] Researching and indexing sources to DB...")
        _t0 = monotonic()

        research_cache_path = research_dir / f"{today_str}-{slug}-research.json"

        if (research_dir / draft_filename).exists() or (research_dir / edited_filename).exists():
            logger.info("Draft already exists — skipping research step.")
            research_output = "{}"
        elif research_cache_path.exists():
            logger.info("Research cache found — loading from %s", research_cache_path.name)
            research_output = research_cache_path.read_text(encoding="utf-8")
        else:
            # --- Pre-fetch: generate 2-3 queries and index pages BEFORE the LLM ---
            logger.info("Pre-fetching pages into corpus before Researcher LLM call...")
            try:
                from pipeline.tools.search import _prefetch_topic
                await _prefetch_topic(topic, num_queries=2)
                logger.info("Pre-fetch complete.")
            except Exception as _pf_err:
                logger.warning("Pre-fetch failed (non-fatal): %s", _pf_err)

            research_input = (
                f"Research this topic thoroughly for a blog post: {topic}\n\n"
                f"The knowledge corpus has already been seeded with pages on this topic.\n"
                f"REQUIRED STEPS:\n"
                f"1. Generate 2-3 targeted search queries covering different angles.\n"
                f"2. For each query call search_and_index to fetch and store any new pages.\n"
                f"3. Call search_corpus ONCE with top_k=3 to retrieve the stored knowledge.\n"
                f"4. Return structured research JSON with key_findings, subtopics, "
                f"suggested_angles, gaps, source_list, total_sources, model_used."
            )
            research_output, r_tin, r_tout = await _run_agent_with_fallback(
                researcher, research_input,
                agent_name="Researcher", pool=pool, max_turns=8, run_log=run_log,
            )
            await log_model_call(pool, researcher.model, tokens_in=r_tin, tokens_out=r_tout, phase="research")
            logger.info("Research complete (tokens: in=%d out=%d).", r_tin, r_tout)

            # Cache research JSON locally to avoid re-running on retry
            try:
                research_cache_path.write_text(research_output, encoding="utf-8")
                logger.info("Research JSON cached to %s", research_cache_path.name)
            except Exception as _cache_err:
                logger.warning("Could not cache research JSON: %s", _cache_err)

        # Persist research JSON to corpus
        research_doc_name = f"{today_str}-{slug}-research"
        try:
            from pipeline.tools.corpus import _index_document_impl
            await _index_document_impl(
                content=research_output,
                source=research_doc_name,
                doc_type="research",
            )
            logger.info("Research JSON saved to DB as '%s'", research_doc_name)
        except Exception as _idx_err:
            logger.warning("Could not save research to DB: %s", _idx_err)

        run_log.stage_ok("Research", elapsed_s=round(monotonic() - _t0, 1), model=researcher.model)
        logger.info("[1/5] Research done in %.1fs", monotonic() - _t0)

        # =============================================================
        # Step 2: Write draft
        # =============================================================
        _current_stage = "Write"
        run_log.stage_start("Write")
        logger.info("[2/5] Writing draft (cooldown %ds)...", _STAGE_COOLDOWN)
        await asyncio.sleep(_STAGE_COOLDOWN)
        _t0 = monotonic()
        # Writer needs full context: all subtopics, angles, and source URLs
        research_compact_writer = _compact_research(research_output, max_chars=8000)
        # Editor only needs key findings + sources for fact-checking; it reads the draft directly.
        # Keep this small — the draft itself (~2,500 tokens) plus system prompt already uses
        # most of gpt-4.1's 8,000-token request limit, causing 413 fallbacks to gpt-4.1-mini.
        research_compact_editor = _compact_research(research_output, max_chars=1500)

        if (research_dir / draft_filename).exists():
            logger.info("Draft already exists, skipping writer: %s", draft_filename)
        else:
            existing_drafts = set(research_dir.glob("*.md"))

            write_input = (
                f"Write a blog post about: {topic}\n"
                f"You MUST call write_research_file with filename '{draft_filename}' "
                f"to save the post before you finish — do not stop without saving.\n\n"
                f"Research findings:\n{research_compact_writer}"
            )
            _, w_tin, w_tout = await _run_agent_with_fallback(
                writer, write_input,
                agent_name="Writer", pool=pool, max_turns=6, run_log=run_log,
            )
            await log_model_call(pool, writer.model, tokens_in=w_tin, tokens_out=w_tout, phase="writer")

            new_drafts = [
                f for f in research_dir.glob("*.md")
                if f not in existing_drafts and "-edited" not in f.name
            ]
            if not new_drafts:
                logger.warning("Writer did not save a file — retrying with explicit instruction...")
                retry_input = (
                    f"Write a blog post about: {topic}\n"
                    f"Save the post by calling write_research_file with filename '{draft_filename}'.\n\n"
                    f"Research findings:\n{research_compact_writer}"
                )
                _, wr_tin, wr_tout = await _run_agent_with_fallback(
                    writer, retry_input,
                    agent_name="Writer", pool=pool, max_turns=6, run_log=run_log,
                )
                await log_model_call(pool, writer.model, tokens_in=wr_tin, tokens_out=wr_tout, phase="writer-retry")
                new_drafts = [
                    f for f in research_dir.glob("*.md")
                    if f not in existing_drafts and "-edited" not in f.name
                ]

            if new_drafts:
                draft_filename = max(new_drafts, key=lambda f: f.stat().st_mtime).name

        logger.info("Draft saved: %s", draft_filename)
        run_log.stage_ok("Write", elapsed_s=round(monotonic() - _t0, 1), draft=draft_filename)
        logger.info("[2/5] Write done in %.1fs", monotonic() - _t0)

        # =============================================================
        # Step 3: Edit
        # =============================================================
        _current_stage = "Edit"
        run_log.stage_start("Edit")
        # Adaptive cooldown: query RPM usage and wait only if needed.
        # If the model's RPM window is clear, use the standard cooldown;
        # otherwise wait long enough for the window to rotate.
        from pipeline.guardrails import get_rpm_usage, RPM_LIMITS
        _editor_model = editor.model
        try:
            rpm_used = await get_rpm_usage(pool, _editor_model)
            rpm_limit = RPM_LIMITS.get(_editor_model, 10)
            if rpm_used >= rpm_limit - 1:  # within 1 of the limit
                _editor_cooldown = 60
                logger.info("[3/5] RPM pressure on %s (%d/%d) — cooling %ds",
                            _editor_model, rpm_used, rpm_limit, _editor_cooldown)
            else:
                _editor_cooldown = _STAGE_COOLDOWN
                logger.info("[3/5] RPM clear on %s (%d/%d) — standard cooldown %ds",
                            _editor_model, rpm_used, rpm_limit, _editor_cooldown)
        except Exception:
            _editor_cooldown = 60  # safe default on DB failure
            logger.info("[3/5] RPM check failed — using safe cooldown %ds", _editor_cooldown)
        logger.info("[3/5] Editing (cooldown %ds)...", _editor_cooldown)
        await asyncio.sleep(_editor_cooldown)
        _t0 = monotonic()

        if (research_dir / edited_filename).exists():
            logger.info("Edited file already exists, skipping editor: %s", edited_filename)
        else:
            edit_input = (
                f"Edit the blog post draft.\n"
                f"1. Call read_research_file('{draft_filename}') to read the draft.\n"
                f"2. Save your edits as '{edited_filename}' using write_research_file.\n\n"
                f"Research findings for fact-checking:\n{research_compact_editor}\n\n"
                f"If you need to verify additional claims, call search_corpus with a "
                f"relevant query to check the knowledge base."
            )
            try:
                _, e_tin, e_tout = await _run_agent_with_fallback(
                    editor, edit_input,
                    agent_name="Editor", pool=pool, max_turns=6, run_log=run_log,
                )
                await log_model_call(pool, editor.model, tokens_in=e_tin, tokens_out=e_tout, phase="editor")
            except asyncio.TimeoutError as _te:
                run_log.warning("Edit", f"Editor timed out after {_AGENT_TIMEOUT}s")
                logger.error("Editor timed out after %ds", _AGENT_TIMEOUT)

            # Verify the editor actually saved the file
            if not (research_dir / edited_filename).exists():
                run_log.warning("Edit", "Editor did not save — using unedited draft as fallback",
                                fallback=draft_filename)
                logger.warning(
                    "Editor did not produce '%s' — falling back to unedited draft.",
                    edited_filename,
                )
                edited_filename = draft_filename

        logger.info("Edit complete: %s", edited_filename)
        run_log.stage_ok("Edit", elapsed_s=round(monotonic() - _t0, 1), edited=edited_filename)
        logger.info("[3/5] Edit done in %.1fs", monotonic() - _t0)

        # =============================================================
        # Step 4: Publish
        # =============================================================
        _current_stage = "Publish"
        run_log.stage_start("Publish")
        logger.info("[4/5] Publishing to Ghost (cooldown %ds)...", _STAGE_COOLDOWN)
        await asyncio.sleep(_STAGE_COOLDOWN)
        _t0 = monotonic()

        publish_input = _build_publish_input(edited_filename)
        publish_output, p_tin, p_tout = await _run_agent_with_fallback(
            publisher, publish_input,
            agent_name="Publisher", pool=pool, max_turns=6, run_log=run_log,
        )
        await log_model_call(pool, publisher.model, tokens_in=p_tin, tokens_out=p_tout, phase="publisher")

        # --- Handle MISSING: validation failures from publish_file_to_ghost ---
        if publish_output.strip().startswith("MISSING:"):
            logger.warning("Publish blocked — pre-publish validation failed: %s", publish_output)
            missing_lower = publish_output.lower()

            if any(kw in missing_lower for kw in (
                "title", "body_content", "just for laughs", "source links", "excerpt"
            )):
                logger.info("Recovering: re-running Editor to fix content issues...")
                recovery_input = (
                    f"The blog post FAILED pre-publish validation with this error:\n"
                    f"{publish_output}\n\n"
                    f"Fix ALL reported issues before saving:\n"
                    f"- If 'title' issue: rewrite to be 5–10 words, factual, punchy.\n"
                    f"- If 'body_content' too short: expand to at least 900 words.\n"
                    f"- If 'Just For Laughs' missing: add a ## Just For Laughs section.\n"
                    f"- If 'source links' missing: add inline markdown links.\n"
                    f"- If 'excerpt' missing: add a 1–2 sentence excerpt in frontmatter.\n\n"
                    f"1. Call read_research_file('{draft_filename}') to read the original draft.\n"
                    f"2. Fix every reported validation issue.\n"
                    f"3. Save the corrected post as '{edited_filename}' using write_research_file."
                )
                _, er_tin, er_tout = await _run_agent_with_fallback(
                    editor, recovery_input,
                    agent_name="Editor", pool=pool, max_turns=10, run_log=run_log,
                )
                await log_model_call(pool, editor.model, tokens_in=er_tin, tokens_out=er_tout, phase="editor-recovery")

            logger.info("Retrying Publisher after recovery...")
            publish_output, pr_tin, pr_tout = await _run_agent_with_fallback(
                publisher, publish_input,
                agent_name="Publisher", pool=pool, max_turns=6, run_log=run_log,
            )
            await log_model_call(pool, publisher.model, tokens_in=pr_tin, tokens_out=pr_tout, phase="publisher-retry")

            if publish_output.strip().startswith("MISSING:"):
                raise RuntimeError(
                    f"Pipeline aborted — publish validation still failing after recovery.\n"
                    f"Unresolved: {publish_output}"
                )

        logger.info("Published: %s", publish_output)
        run_log.stage_ok("Publish", elapsed_s=round(monotonic() - _t0, 1), url=publish_output)
        logger.info("[4/5] Publish done in %.1fs", monotonic() - _t0)

        # =============================================================
        # Step 5: Index to corpus
        # =============================================================
        _current_stage = "Index"
        run_log.stage_start("Index")
        logger.info("[5/5] Indexing edited post to corpus (cooldown %ds)...", _STAGE_COOLDOWN)
        await asyncio.sleep(_STAGE_COOLDOWN)
        _t0 = monotonic()

        # Bypass the Indexer agent — call _index_document_impl directly.
        # Running an LLM for this step causes 413 Payload Too Large because the
        # SDK sends the full conversation (file content read + content in
        # index_document args) exceeding GitHub Models' request body limit.
        from pipeline.tools.corpus import _index_document_impl
        edited_path = research_dir / edited_filename
        if edited_path.exists():
            article_text = edited_path.read_text(encoding="utf-8")
            index_output = await _index_document_impl(
                content=article_text,
                source=f"{today_str}-{slug}",
                doc_type="article",
                date=today_str,
            )
        else:
            index_output = f"Skipped indexing — edited file not found: {edited_filename}"
            logger.warning("Skipped indexing: %s not found", edited_filename)

        _total = monotonic() - _pipeline_t0
        run_log.stage_ok("Index", elapsed_s=round(monotonic() - _t0, 1), detail=index_output)
        logger.info("[5/5] Index done in %.1fs", monotonic() - _t0)
        logger.info("BLOG pipeline complete in %.1fs (%.1f min)", _total, _total / 60)
        logger.info("Published: %s", publish_output)
        logger.info("Corpus: %s", index_output)
        run_log.run_complete(published_url=publish_output, total_elapsed_s=_total)
        _pipeline_result = {
            "status": "published",
            "published_url": publish_output,
            "run_log": run_log,
            "total_elapsed_s": _total,
        }
    except Exception as exc:
        _total = monotonic() - _pipeline_t0
        run_log.stage_error(_current_stage, exc)
        run_log.run_failed(_current_stage, exc, total_elapsed_s=_total)
        _pipeline_result = {
            "status": "failed",
            "published_url": "",
            "run_log": run_log,
            "total_elapsed_s": _total,
        }
        logger.error(
            "BLOG pipeline failed at stage '%s': %s",
            _current_stage, exc, exc_info=True,
        )
    finally:
        await close_pool()

    return _pipeline_result


async def _run_publish_only(task: str, debug: bool = False) -> None:
    """Run only the Publisher step for an already-edited file.

    Usage:  python -m pipeline.main "PUBLISH: 2026-03-13-my-post-edited.md"
    """
    from pipeline.setup import init_github_models
    from pipeline.definitions import publisher
    from pipeline.db import get_pool, close_pool

    init_github_models()

    # Disable tracing — GitHub token is not a valid OpenAI key
    import os as _os
    _os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"

    filename = task.partition(":")[2].strip()
    logger.info("Publishing '%s'...", filename)

    try:
        pool = await get_pool()
        publish_input = _build_publish_input(filename)
        publish_output, _, _ = await _run_agent_with_fallback(
            publisher, publish_input,
            agent_name="Publisher", pool=pool, max_turns=6,
        )
        logger.info("Result: %s", publish_output)
    finally:
        await close_pool()


async def _run_research_pipeline(task: str, debug: bool = False) -> None:
    """Run RESEARCH or REPORT: Research + Index, no blog post."""
    from pipeline.setup import init_github_models
    from pipeline.definitions import researcher
    from pipeline.db import get_pool, close_pool
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

        research_input = (
            f"Research this topic thoroughly: {topic}\n\n"
            f"REQUIRED STEPS:\n"
            f"1. Generate 2-3 search queries covering different angles.\n"
            f"2. For each query call search_and_index.\n"
            f"3. Call search_corpus after indexing.\n"
            f"5. Return structured research JSON."
        )
        research_output, r_tin, r_tout = await _run_agent_with_fallback(
            researcher, research_input,
            agent_name="Researcher", pool=pool, max_turns=8,
        )
        await log_model_call(pool, researcher.model, tokens_in=r_tin, tokens_out=r_tout, phase="research")
        logger.info("Research complete (tokens: in=%d out=%d)", r_tin, r_tout)

        # Index to corpus — bypass Indexer agent to avoid 413 Payload Too Large
        logger.info("Indexing research to corpus (direct)...")
        from pipeline.tools.corpus import _index_document_impl
        index_output = await _index_document_impl(
            content=research_output,
            source=f"{today_str}-{slug}-research",
            doc_type="research",
        )

        logger.info("%s pipeline complete", prefix.strip().upper())
        logger.info("Corpus: %s", index_output)
    finally:
        await close_pool()


async def _run_index(task: str) -> None:
    """Handle INDEX: path — extract text, check dedup, index to corpus.

    Supports files in research/, reports/, or any path relative to the project root.
    PDFs are extracted via pypdf.  Files already present in the corpus are skipped.
    """
    import pathlib
    from datetime import date
    from pipeline.tools.corpus import _index_document_impl, _is_source_indexed
    from pipeline.db import close_pool
    from pipeline.setup import init_github_models

    init_github_models()

    raw_path = task[len("INDEX:"):].strip()
    project_root = pathlib.Path(__file__).parent.parent
    file_path = (project_root / raw_path).resolve()

    if not file_path.exists():
        print(f"File not found: {raw_path}")
        await close_pool()
        return

    # Use the normalised relative path as the dedup source key.
    try:
        source = str(file_path.relative_to(project_root))
    except ValueError:
        source = raw_path

    try:
        already_indexed = await _is_source_indexed(source)
    except Exception as exc:
        logger.warning("Could not check dedup status: %s", exc)
        already_indexed = False

    if already_indexed:
        print(f"Already indexed — skipping: {source}")
        await close_pool()
        return

    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(file_path))
            pages = [page.extract_text() or "" for page in reader.pages]
            content = "\n\n".join(p for p in pages if p.strip())
        except Exception as exc:
            print(f"PDF extraction failed for {raw_path}: {exc}")
            await close_pool()
            return
    else:
        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            print(f"Could not read {raw_path}: {exc}")
            await close_pool()
            return

    if not content.strip():
        print(f"No extractable content in: {raw_path}")
        await close_pool()
        return

    doc_type = "pdf" if suffix == ".pdf" else "article"
    doc_date = str(date.today())

    logger.info("Indexing %s (%s chars)...", source, len(content))
    try:
        result = await _index_document_impl(content, source, doc_type, doc_date)
        print(result)
    except Exception as exc:
        print(f"Indexing failed: {exc}")
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
        help="Override the orchestrator model (e.g. openai/gpt-4.1-mini)",
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
