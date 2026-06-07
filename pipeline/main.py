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
# Pipeline run notification emails
# ---------------------------------------------------------------------------

def _send_pipeline_notification(subject: str, body: str) -> None:
    """Send a plain-text notification email to NOTIFY_EMAIL (if set).

    Uses the same Hostinger SMTP credentials as email_listener.py.
    Logs and swallows errors — a notification failure must never kill the pipeline.
    """
    import smtplib
    import email.mime.multipart
    import email.mime.text

    notify_email = os.environ.get("NOTIFY_EMAIL", "").strip()
    if not notify_email:
        return

    smtp_host = os.environ.get("SMTP_HOST", "smtp.hostinger.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER") or os.environ.get("EMAIL_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS") or os.environ.get("EMAIL_PASS", "")
    from_addr = smtp_user or "admin@beyondtomorrow.world"

    if not smtp_user or not smtp_pass:
        logger.warning("SMTP credentials not set — skipping pipeline notification to %s", notify_email)
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
        logger.info("Pipeline notification sent to %s: %s", notify_email, subject)
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


def _is_413_error(exc: Exception) -> bool:
    """Return True specifically for HTTP 413 (Payload Too Large) errors.

    Used to trigger a same-model retry with reduced max_tokens before
    falling back to a cheaper model.
    """
    from openai import APIStatusError

    if isinstance(exc, APIStatusError) and exc.status_code == 413:
        return True
    msg = str(exc)
    return "Request body too large" in msg


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
    # Before immediately switching to a cheaper model, check whether the
    # RPM window for the preferred model will clear within 90s.  If so,
    # wait and keep the preferred model rather than falling back.
    from pipeline.guardrails import check_model_budget, get_rpm_clear_wait
    try:
        selected = await select_model(current_model, pool=pool)
        if selected != current_model:
            # Only switched because of RPM pressure — check if we should just wait
            try:
                budget = await check_model_budget(pool, current_model)
                if budget.get("rpm_exceeded") and not (budget.get("pct", 0) >= 95):
                    # RPM-only block; daily budget is fine — wait for window
                    wait_s = await get_rpm_clear_wait(pool, current_model, max_wait=90)
                    if wait_s < 90:
                        logger.info(
                            "%s: RPM window for %s clears in %ds — waiting to avoid fallback",
                            agent_name, current_model, wait_s,
                        )
                        await asyncio.sleep(wait_s)
                        selected = current_model  # keep preferred model
            except Exception:
                pass  # if the check fails, use whatever select_model chose

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
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                result = await asyncio.wait_for(
                    Runner.run(agent, max_turns=max_turns, input=input_text),
                    timeout=_AGENT_TIMEOUT,
                )
                tokens_in, tokens_out = _extract_usage(result)
                return result.final_output, tokens_in, tokens_out
            except asyncio.TimeoutError:
                logger.warning(
                    "%s timed out after %ds (attempt %d/%d)",
                    agent_name, _AGENT_TIMEOUT, attempt + 1, max_attempts,
                )
                if attempt + 1 >= max_attempts:
                    raise
                # First timeout: retry same model; subsequent: fall back
                if attempt > 0:
                    fallback = get_fallback(current_model)
                    if fallback:
                        logger.warning(
                            "%s: repeated timeout on %s — falling back to %s",
                            agent_name, current_model, fallback,
                        )
                        if run_log:
                            run_log.model_fallback(
                                stage=agent_name, agent_name=agent_name,
                                from_model=current_model, to_model=fallback,
                                attempt=attempt + 1,
                                reason=f"TimeoutError after {_AGENT_TIMEOUT}s",
                            )
                        current_model = fallback
                        agent.model = current_model
                        agent.model_settings = model_settings_for(
                            agent_name.lower(), model_override=current_model
                        )
                backoff = min(_RETRY_BACKOFF_BASE * (2 ** attempt), 300)
                logger.info("%s: retrying in %ds...", agent_name, backoff)
                await asyncio.sleep(backoff)
                continue
            except Exception as exc:
                if _is_rate_limit_error(exc):
                    # --- 413 same-model retry: reduce max_tokens before falling back ---
                    # A 413 means the request body (input + max_tokens) exceeded the
                    # GitHub Models API limit. Retrying on the same model with reduced
                    # max_tokens preserves output quality; falling back to gpt-4.1-mini
                    # risks C1 punctuation corruption.
                    if _is_413_error(exc) and not getattr(agent, "_413_retried", False):
                        current_mt = getattr(agent.model_settings, "max_tokens", None)
                        if current_mt and current_mt > 1500:
                            reduced_mt = max(current_mt - 500, 1500)
                            logger.warning(
                                "%s hit 413 on %s — retrying SAME model with "
                                "max_tokens %d → %d before falling back",
                                agent_name, current_model, current_mt, reduced_mt,
                            )
                            from agents import ModelSettings
                            agent.model_settings = ModelSettings(
                                temperature=agent.model_settings.temperature,
                                max_tokens=reduced_mt,
                            )
                            agent._413_retried = True  # noqa: SLF001
                            await asyncio.sleep(5)
                            continue  # retry same attempt slot

                    # Before permanently downgrading, check if we just need
                    # to wait for the rolling 60s RPM window to clear.  A
                    # < 90s wait is cheaper than falling back to mini for the
                    # entire remaining pipeline.
                    # NOTE: only take this path when wait_s > 0 (genuine RPM
                    # pressure detected).  If wait_s == 0, the RPM tracker
                    # sees no pressure but we still got a 429 — that means
                    # a TPM/daily limit, not RPM.  Retrying immediately on the
                    # same model would spin all 6 attempts without ever
                    # falling back.
                    if not _is_413_error(exc):
                        try:
                            wait_s = await get_rpm_clear_wait(pool, current_model, max_wait=90)
                            if 0 < wait_s < 90:
                                logger.info(
                                    "%s: RPM window for %s clears in %ds — "
                                    "waiting to avoid fallback (attempt %d/%d)",
                                    agent_name, current_model, wait_s,
                                    attempt + 1, max_attempts,
                                )
                                await asyncio.sleep(wait_s)
                                continue  # retry same model
                            # wait_s == 0: no RPM pressure but 429 still fired
                            # → TPM/daily limit; fall through to model fallback
                        except Exception:
                            pass  # check failed — fall through to normal backoff

                    last_exc = exc
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
                        last_exc = exc
                        raise RuntimeError(
                            f"{agent_name} failed — rate-limited on every model in "
                            f"the fallback chain. Last model: {current_model}"
                        ) from exc
                else:
                    last_exc = exc
                    raise

        err_msg = f"{agent_name} failed after {max_attempts} attempts"
        if last_exc is not None:
            err_msg += f" — last error: {type(last_exc).__name__}: {last_exc}"
        raise RuntimeError(err_msg)
    finally:
        # Always restore original model so fallback doesn't leak to next stage
        agent.model = original_model
        agent.model_settings = original_settings
        # Clean up 413 retry flag
        if hasattr(agent, "_413_retried"):
            del agent._413_retried


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


async def _sanitise_research_sources(research_json: str) -> str:
    """Strip dead/fabricated URLs from a research JSON string before indexing.

    LLMs sometimes hallucinate plausible-looking source URLs.  These get
    indexed into the corpus and re-cited by the Researcher on subsequent
    runs.  This function:

    1. Parses the research JSON.
    2. Collects every URL from ``source_list`` and ``key_findings[].sources``.
    3. Concurrently validates each URL with a HEAD request (5 s timeout).
    4. Removes any URL that returns 4xx/5xx, fails to connect, or is not
       an http/https URL.
    5. Returns the cleaned JSON string (or the original if parsing fails).

    Non-fatal — any exception returns the original string unchanged.
    """
    import json as _json
    import asyncio as _asyncio

    def _is_http(url: str) -> bool:
        return isinstance(url, str) and url.startswith(("http://", "https://"))

    try:
        data = _json.loads(research_json)
    except Exception:
        return research_json  # not JSON — leave unchanged

    # Collect all unique URLs that need checking
    all_urls: set[str] = set()
    for src in data.get("source_list", []):
        if _is_http(src.get("url", "")):
            all_urls.add(src["url"])
    for finding in data.get("key_findings", []):
        for url in finding.get("sources", []):
            if _is_http(url):
                all_urls.add(url)

    if not all_urls:
        return research_json

    # Validate URLs concurrently
    async def _check(url: str) -> tuple[str, bool]:
        try:
            import httpx as _httpx
            async with _httpx.AsyncClient(
                timeout=5.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 (compatible; BeyondTomorrow/1.0)"},
            ) as client:
                try:
                    resp = await client.head(url)
                except Exception:
                    resp = await client.get(url)  # some servers reject HEAD
                return url, resp.status_code < 400
        except Exception:
            return url, False

    results = await _asyncio.gather(*[_check(u) for u in all_urls], return_exceptions=False)
    dead = {url for url, ok in results if not ok}

    if not dead:
        return research_json  # all URLs live — no changes needed

    logger.info(
        "Stripping %d dead source URL(s) from research JSON: %s",
        len(dead), list(dead),
    )

    # Remove dead URLs from source_list
    data["source_list"] = [
        s for s in data.get("source_list", [])
        if s.get("url", "") not in dead
    ]
    data["total_sources"] = len(data.get("source_list", []))

    # Remove dead URLs from key_findings[].sources
    for finding in data.get("key_findings", []):
        finding["sources"] = [
            u for u in finding.get("sources", []) if u not in dead
        ]

    return _json.dumps(data, ensure_ascii=False, indent=2)


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
        f"Publish the blog post file '{filename}' to Ghost.\n"
        f"Step 1: call pick_random_asset_image()\n"
        f"Step 2: call upload_image_to_ghost(image_path=<path from step 1>)\n"
        f"Step 3: call publish_file_to_ghost(filename='{filename}', "
        f"feature_image_url=<url from step 2>, status='published')\n"
        f"Step 4: return EXACTLY: PUBLISHED: <ghost_url from step 3> | FEATURE_IMAGE: <url from step 2>"
    )


def _parse_publish_output(publish_output: str) -> tuple[str, str]:
    """Extract (ghost_url, feature_image_url) from publisher agent output.

    Returns ('', '') if not parseable.
    """
    import re as _re
    ghost_url = ""
    feature_image_url = ""
    # Look for PUBLISHED: <url> marker first (structured format)
    m = _re.search(r'PUBLISHED:\s*(https://[^\s|]+)', publish_output, _re.IGNORECASE)
    if m:
        ghost_url = m.group(1).rstrip("/") + "/"
    else:
        # Fallback: any beyondtomorrow.world URL
        m = _re.search(r'(https://beyondtomorrow\.world/[^\s|]+)', publish_output)
        if m:
            ghost_url = m.group(1)
    # Feature image
    m = _re.search(r'FEATURE_IMAGE:\s*(https://[^\s|\n]+)', publish_output, _re.IGNORECASE)
    if m:
        feature_image_url = m.group(1)
    else:
        # Fallback: look for feature_image in publish_file_to_ghost return embedded in output
        m = _re.search(r'feature[_-]?image:\s*(https://[^\s|\n]+)', publish_output, _re.IGNORECASE)
        if m:
            feature_image_url = m.group(1)
    return ghost_url, feature_image_url


async def _linkedin_post_direct(
    ghost_url: str,
    feature_image_url: str,
    edited_path,
    run_log=None,
) -> str:
    """Post a published Ghost article to LinkedIn by reading frontmatter directly.

    Called from main.py after the publisher step — keeps the LLM out of the
    LinkedIn loop entirely so excerpt/tags are always read from the actual file.
    Returns the LinkedIn result string.
    """
    from pathlib import Path
    from pipeline.tools.linkedin import _post_to_linkedin_impl
    from pipeline.tools.ghost import _parse_frontmatter

    try:
        raw = Path(edited_path).read_text(encoding="utf-8")
        meta, _ = _parse_frontmatter(raw)
    except Exception as exc:
        logger.warning("LinkedIn direct: could not read frontmatter from %s: %s", edited_path, exc)
        return f"SKIPPED: could not read frontmatter — {exc}"

    title = meta.get("title", "").strip()
    excerpt = meta.get("excerpt", "").strip()
    tags = meta.get("tags", "").strip()

    if not title or not excerpt:
        logger.warning("LinkedIn direct: missing title or excerpt in frontmatter — skipping.")
        return "SKIPPED: missing title or excerpt in frontmatter"

    logger.info("LinkedIn direct: posting '%s' → %s", title, ghost_url)
    try:
        result = await _post_to_linkedin_impl(
            title=title,
            excerpt=excerpt,
            post_url=ghost_url,
            tags=tags,
            feature_image_url=feature_image_url,
        )
    except Exception as exc:
        result = f"Error: {exc}"
        logger.error("LinkedIn direct: unexpected error: %s", exc)

    logger.info("LinkedIn direct result: %s", result)
    if run_log:
        run_log.stage_ok("LinkedIn", url=ghost_url, result=result)
    return result


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


async def _fix_title_via_llm(openai_client, edited_path) -> bool:
    """Rewrite an over-long title in-place using a minimal LLM call (~30 tokens).

    Reads the current title from frontmatter, asks the model to shorten it to
    5-10 words, then patches the file.  Returns True if the title was updated.
    """
    import re as _re
    raw = edited_path.read_text(encoding="utf-8")
    m = _re.search(r"^title:\s*(.+)$", raw, _re.MULTILINE)
    if not m:
        return False
    old_title = m.group(1).strip()
    if len(old_title.split()) <= 10:
        return False  # already fine — nothing to do

    logger.info("Fixing title via LLM: %r (%d words)", old_title, len(old_title.split()))
    try:
        resp = await openai_client.chat.completions.create(
            model="openai/gpt-4.1-mini",
            max_tokens=30,
            temperature=0.3,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You rewrite blog post titles. "
                        "Return ONLY the new title — no explanation, no quotes."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f'Rewrite this title as a punchy, thought-provoking headline '
                        f'of 5 to 10 words maximum. It must make the reader feel something '
                        f'is at stake — use tension, contrast, or an implied revelation. '
                        f'Keep the core meaning intact and accurate.\n\n'
                        f'Original: {old_title}'
                    ),
                },
            ],
        )
        new_title = resp.choices[0].message.content.strip().strip('"').strip("'")
        if not new_title or not (5 <= len(new_title.split()) <= 10):
            logger.warning("LLM title fix returned unusable result: %r", new_title)
            return False
        patched = raw[:m.start(1)] + new_title + raw[m.end(1):]
        edited_path.write_text(patched, encoding="utf-8")
        logger.info("Title fixed: %r", new_title)
        return True
    except Exception as exc:
        logger.warning("LLM title fix failed (%s) — will fall back to Editor", exc)
        return False


async def _run_blog_pipeline(task: str, debug: bool = False) -> dict:
    """Run the full BLOG pipeline: Research+Index → Write → Edit → Publish → Index."""
    from pathlib import Path

    from pipeline._sdk import Runner
    from pipeline.setup import init_github_models
    from pipeline.definitions import researcher, writer, editor, publisher, indexer, model_settings_for
    from pipeline.db import get_pool, close_pool
    from pipeline.degradation import select_model
    from pipeline.guardrails import log_model_call

    _openai_client = init_github_models()

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

    # Notify personal email that the pipeline has started
    _send_pipeline_notification(
        subject=f"[BeyondTomorrow] Starting BLOG: {topic}",
        body=(
            f"Command  : BLOG\n"
            f"Topic    : {topic}\n"
            f"Status   : Pipeline started\n"
            f"Started  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Stages pending: Research → Write → Edit → Publish → Index\n"
            f"You will receive a follow-up email when the pipeline completes."
        ),
    )

    # Pre-flight: warn early if LinkedIn is not configured so it's visible
    # in Railway logs before the pipeline runs (not discovered at the end).
    _li_token_pf = os.environ.get("LINKEDIN_ACCESS_TOKEN", "").strip()
    _li_urn_pf = os.environ.get("LINKEDIN_PERSON_URN", "").strip()
    if not _li_token_pf or not _li_urn_pf:
        logger.warning(
            "PRE-FLIGHT: LinkedIn cross-posting will be SKIPPED — "
            "LINKEDIN_ACCESS_TOKEN and/or LINKEDIN_PERSON_URN are not set. "
            "Set these as Railway service variables to enable LinkedIn publishing."
        )
    else:
        _li_expires_pf = os.environ.get("LINKEDIN_TOKEN_EXPIRES", "").strip()
        if _li_expires_pf:
            try:
                from datetime import date as _date_pf
                _days_pf = (_date_pf.fromisoformat(_li_expires_pf) - _date_pf.today()).days
                if _days_pf <= 0:
                    logger.warning(
                        "PRE-FLIGHT: LinkedIn access token EXPIRED on %s — "
                        "LinkedIn posting will likely fail. Re-run scripts/linkedin_auth.py.",
                        _li_expires_pf,
                    )
                elif _days_pf <= 7:
                    logger.warning(
                        "PRE-FLIGHT: LinkedIn token expires in %d day(s) — refresh soon.",
                        _days_pf,
                    )
            except ValueError:
                pass

    _current_stage = "init"
    _pipeline_t0 = monotonic()
    run_log = None
    _pipeline_result: dict = {
        "status": "failed", "published_url": "", "run_log": None, "total_elapsed_s": 0.0
    }

    try:
        pool = await get_pool()
        from pipeline.pipeline_logger import PipelineRunLogger, set_db_pool, mark_stale_runs_failed
        set_db_pool(pool)

        # Stale-run janitor — close any stuck RUNNING runs before starting this one.
        # stale_after_hours=0 catches runs of any age with no terminal event.
        # Safe because the new run_start is logged AFTER this call.
        try:
            _stale = await mark_stale_runs_failed(pool, stale_after_hours=0)
            if _stale:
                logger.warning(
                    "Stale-run janitor: closed %d orphaned run(s): %s",
                    len(_stale), ", ".join(_stale),
                )
        except Exception as _jex:
            logger.warning("Stale-run janitor error (non-fatal): %s", _jex)

        run_log = PipelineRunLogger(topic=topic, command="BLOG")
        _pipeline_result["run_log"] = run_log
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
            # --- RPM pacing for gpt-4.1 (10 RPM limit) ---
            # The Researcher makes multiple rapid tool-call turns that can
            # exhaust the 10 RPM window. Check RPM usage and add extra
            # cooldown if we're close to the limit.
            try:
                from pipeline.guardrails import get_rpm_usage, RPM_LIMITS
                _res_model = researcher.model
                _res_rpm = await get_rpm_usage(pool, _res_model)
                _res_rpm_limit = RPM_LIMITS.get(_res_model, 10)
                if _res_rpm >= _res_rpm_limit - 2:  # within 2 of limit
                    _res_cooldown = 45
                    logger.info(
                        "RPM pressure on %s (%d/%d) — cooling %ds before Research",
                        _res_model, _res_rpm, _res_rpm_limit, _res_cooldown,
                    )
                    await asyncio.sleep(_res_cooldown)
            except Exception:
                pass  # non-fatal — proactive model selection will handle it

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

            # Strip hallucinated/dead source URLs before caching or indexing —
            # fabricated URLs would otherwise be stored in the corpus and
            # re-cited by the Researcher on the next pipeline run.
            try:
                research_output = await _sanitise_research_sources(research_output)
            except Exception as _san_err:
                logger.warning("Source sanitisation failed (non-fatal): %s", _san_err)

            # Cache research JSON locally to avoid re-running on retry
            try:
                research_cache_path.write_text(research_output, encoding="utf-8")
                logger.info("Research JSON cached to %s", research_cache_path.name)
            except Exception as _cache_err:
                logger.warning("Could not cache research JSON: %s", _cache_err)

        # Persist research JSON to corpus — use semantic chunking so each
        # finding and subtopic becomes its own retrievable chunk rather than
        # the entire JSON blob becoming a single oversized chunk.
        research_doc_name = f"{today_str}-{slug}-research"
        try:
            from pipeline.tools.corpus import _index_research_json
            _idx_result = await _index_research_json(
                research_json=research_output,
                source=research_doc_name,
                date=today_str,
            )
            logger.info("Research JSON indexed: %s", _idx_result)
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
        # Reduced from 1500→1200 chars to give ~75 tokens more headroom for longer drafts.
        research_compact_editor = _compact_research(research_output, max_chars=1200)

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
            w_first_output, w_tin, w_tout = await _run_agent_with_fallback(
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
                    f"You are saving a blog post draft. Call write_research_file NOW.\n\n"
                    f"filename: '{draft_filename}'\n\n"
                    f"Write the post about: {topic}\n\n"
                    f"You MUST call write_research_file with the above filename as your FIRST and ONLY action. "
                    f"Do not output any text before the tool call. Do not explain. Just call the tool.\n\n"
                    f"Research findings:\n{research_compact_writer}"
                )
                w_retry_output, wr_tin, wr_tout = await _run_agent_with_fallback(
                    writer, retry_input,
                    agent_name="Writer", pool=pool, max_turns=6, run_log=run_log,
                )
                await log_model_call(pool, writer.model, tokens_in=wr_tin, tokens_out=wr_tout, phase="writer-retry")
                new_drafts = [
                    f for f in research_dir.glob("*.md")
                    if f not in existing_drafts and "-edited" not in f.name
                ]

                # If still no file saved but the output looks like a complete blog post
                # (has YAML frontmatter), persist it directly rather than failing.
                # Check retry output first, then fall back to the first attempt's output.
                _candidate_output = None
                if w_retry_output and w_retry_output.strip().startswith("---"):
                    _candidate_output = w_retry_output
                elif w_first_output and w_first_output.strip().startswith("---"):
                    _candidate_output = w_first_output
                if not new_drafts and _candidate_output:
                    logger.warning(
                        "Writer returned post as text output after two attempts — "
                        "saving final_output as '%s' directly.",
                        draft_filename,
                    )
                    from pipeline.tools.files import _clean_llm_text, _validate_punctuation, _enforce_british_english
                    _saved_content = _enforce_british_english(
                        _validate_punctuation(_clean_llm_text(_candidate_output))
                    )
                    (research_dir / draft_filename).write_text(_saved_content, encoding="utf-8")
                    new_drafts = [research_dir / draft_filename]

            if new_drafts:
                draft_filename = max(new_drafts, key=lambda f: f.stat().st_mtime).name

        # Verify the file actually exists before continuing — if the Writer
        # never called write_research_file (or it failed silently), fail here
        # at the Write stage rather than propagating a missing-file error to
        # the Editor or Publisher two stages later.
        if not (research_dir / draft_filename).exists():
            _write_err = RuntimeError(
                f"Writer did not save '{draft_filename}' after both attempts. "
                "Cannot proceed without a draft file."
            )
            run_log.stage_error("Write", _write_err)
            raise _write_err

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

            # Title-length failure: fix with a single ~30-token LLM call.
            # No need to load the full post — the existing title is all the model needs.
            if "title length" in missing_lower:
                _fixed = await _fix_title_via_llm(_openai_client, research_dir / edited_filename)
                if _fixed:
                    publish_input = _build_publish_input(edited_filename)
                    missing_lower = missing_lower.replace("title length", "")

            if any(kw in missing_lower for kw in (
                "title", "body_content", "just for laughs", "source links", "excerpt",
                "formatting",
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
                    f"- If 'excerpt' missing: add a 1–2 sentence excerpt in frontmatter.\n"
                    f"- If 'formatting' issue: remove any **Case study:** or **Example:** "
                    f"labels and integrate as seamless prose; expand or remove lists with "
                    f"fewer than 3 items; complete or remove any orphaned paragraph fragments.\n\n"
                    f"1. Call read_research_file('{edited_filename}') to read the edited post.\n"
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

        # --- Handle Error: responses from publisher tools ---
        # publish_file_to_ghost, upload_image_to_ghost, and pick_random_asset_image
        # all return "Error: ..." on failure. Treat these as a publish failure so the
        # stage is marked stage_error rather than silently logged as stage_ok.
        if publish_output.strip().startswith("Error:"):
            raise RuntimeError(
                f"Publisher tool returned an error — post was NOT published to Ghost.\n"
                f"Tool output: {publish_output.strip()}"
            )

        logger.info("Published: %s", publish_output)
        run_log.stage_ok("Publish", elapsed_s=round(monotonic() - _t0, 1), url=publish_output)
        logger.info("[4/5] Publish done in %.1fs", monotonic() - _t0)

        # =============================================================
        # Step 4b: LinkedIn (direct — no LLM in the loop)
        # The publisher agent only publishes to Ghost. LinkedIn is handled
        # here by reading frontmatter directly from the edited file, so
        # excerpt and tags are always correct rather than guessed by an LLM.
        #
        # Controls:
        #   - Tracked as a named pipeline stage so failures appear in emails
        #   - Empty ghost_url (parse failure) → stage_error, not silent skip
        #   - Error results → up to 3 retries with 10s/30s backoff
        #   - SKIPPED (not configured) → stage_skipped, not stage_error
        # =============================================================
        _current_stage = "LinkedIn"
        run_log.stage_start("LinkedIn")
        _t0_li = monotonic()
        ghost_url, feature_image_url = _parse_publish_output(publish_output)
        if not ghost_url:
            _li_parse_exc = RuntimeError(
                f"Could not parse Ghost URL from publisher output — "
                f"LinkedIn blocked. Output was: {publish_output[:200]}"
            )
            logger.error("LinkedIn: %s", _li_parse_exc)
            run_log.stage_error("LinkedIn", _li_parse_exc)
            linkedin_result = f"Error: {_li_parse_exc}"
        else:
            edited_path = research_dir / edited_filename
            linkedin_result = ""
            _li_ok = False
            _li_skipped = False
            _li_delays = [10, 30]  # seconds before retry 2, retry 3
            for _li_attempt in range(3):
                if _li_attempt > 0:
                    _li_delay = _li_delays[_li_attempt - 1]
                    logger.info(
                        "LinkedIn: retry %d/3 after %ds...", _li_attempt + 1, _li_delay
                    )
                    await asyncio.sleep(_li_delay)
                # pass run_log=None — we handle stage tracking here
                linkedin_result = await _linkedin_post_direct(
                    ghost_url, feature_image_url, edited_path, run_log=None,
                )
                if linkedin_result.startswith("SKIPPED:"):
                    _li_skipped = True
                    break
                if "Error:" not in linkedin_result:
                    _li_ok = True
                    break
                logger.warning(
                    "LinkedIn attempt %d/3 failed: %s", _li_attempt + 1, linkedin_result
                )

            if _li_skipped:
                _li_skip_reason = linkedin_result.replace("SKIPPED:", "").strip()
                run_log.stage_skipped("LinkedIn", _li_skip_reason)
                logger.info("LinkedIn skipped: %s", _li_skip_reason)
            elif _li_ok:
                run_log.stage_ok(
                    "LinkedIn",
                    elapsed_s=round(monotonic() - _t0_li, 1),
                    result=linkedin_result,
                )
                logger.info("LinkedIn posted: %s", linkedin_result)
            else:
                _li_exc = RuntimeError(linkedin_result)
                run_log.stage_error("LinkedIn", _li_exc)
                logger.error("LinkedIn failed after 3 attempts: %s", linkedin_result)

        publish_output = f"{publish_output} | LinkedIn: {linkedin_result}"

        # =============================================================
        # Step 4c: Newsletter via Resend
        # Sends a per-member email to all subscribed free Ghost members.
        # Non-blocking — failure is logged and tracked but does not abort
        # the pipeline.
        # =============================================================
        _current_stage = "Newsletter"
        run_log.stage_start("Newsletter")
        _t0_nl = monotonic()
        try:
            from pipeline.tools.newsletter import send_newsletter
            _nl_fm = {}
            try:
                import re as _re_nl
                import yaml as _yaml_nl
                _raw_nl = (research_dir / edited_filename).read_text(encoding="utf-8")
                _fm_match = _re_nl.match(r"^---\s*\n(.*?)\n---", _raw_nl, _re_nl.DOTALL)
                if _fm_match:
                    _parsed = _yaml_nl.safe_load(_fm_match.group(1)) or {}
                    _nl_fm = {str(k).lower(): str(v).strip() if v is not None else "" for k, v in _parsed.items()}
                else:
                    # Fallback: regex scan (no char limit)
                    for _k, _v in _re_nl.findall(r"^(\w+):\s*(.+)$", _raw_nl, _re_nl.MULTILINE):
                        _nl_fm[_k.lower()] = _v.strip()
            except Exception:
                pass
            _nl_title = _nl_fm.get("title", "")
            _nl_excerpt = _nl_fm.get("excerpt", "")
            newsletter_result = await send_newsletter(
                post_url=ghost_url,
                title=_nl_title or topic,
                excerpt=_nl_excerpt,
                feature_image_url=feature_image_url or "",
            )
        except Exception as _nl_exc:
            newsletter_result = f"Error: {_nl_exc}"

        if newsletter_result.startswith("SKIPPED:"):
            run_log.stage_skipped("Newsletter", newsletter_result.replace("SKIPPED:", "").strip())
            logger.info("Newsletter skipped: %s", newsletter_result)
        elif newsletter_result.startswith("Error:"):
            run_log.stage_error("Newsletter", RuntimeError(newsletter_result))
            logger.error("Newsletter failed: %s", newsletter_result)
        else:
            run_log.stage_ok("Newsletter", elapsed_s=round(monotonic() - _t0_nl, 1), result=newsletter_result)
            logger.info("Newsletter: %s", newsletter_result)

        publish_output = f"{publish_output} | Newsletter: {newsletter_result}"

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
                source=ghost_url or f"{today_str}-{slug}",
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
        # Notify personal email: pipeline succeeded
        _mins = _total / 60
        _send_pipeline_notification(
            subject=f"[BeyondTomorrow] Published: {topic}",
            body=(
                f"Command  : BLOG\n"
                f"Topic    : {topic}\n"
                f"Status   : Published\n"
                f"URL      : {publish_output}\n"
                f"Duration : {int(_total // 60)}m {int(_total % 60)}s\n"
                f"\nStages:\n{_fmt_pipeline_stages(run_log)}"
            ),
        )
    except Exception as exc:
        _total = monotonic() - _pipeline_t0
        if run_log is not None:
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
        # Notify personal email: pipeline failed
        _send_pipeline_notification(
            subject=f"[BeyondTomorrow] FAILED: BLOG: {topic}",
            body=(
                f"Command  : BLOG\n"
                f"Topic    : {topic}\n"
                f"Status   : FAILED at {_current_stage}\n"
                f"Error    : {type(exc).__name__}: {exc}\n"
                f"Duration : {int(_total // 60)}m {int(_total % 60)}s\n"
                f"\nStages:\n{_fmt_pipeline_stages(run_log)}"
            ),
        )
    finally:
        # Let fire-and-forget DB writes (run_failed, stage_error) flush
        # before closing the connection pool.
        await asyncio.sleep(0.5)
        await close_pool()

    return _pipeline_result


async def _run_publish_only(task: str, debug: bool = False) -> None:
    """Run only the Publisher step for an already-edited file.

    Usage:  python -m pipeline.main "PUBLISH: 2026-03-13-my-post-edited.md"
    """
    from pipeline.setup import init_github_models
    from pipeline.definitions import publisher
    from pipeline.db import get_pool, close_pool
    from pathlib import Path as _Path

    _openai_client = init_github_models()

    # Disable tracing — GitHub token is not a valid OpenAI key
    import os as _os
    _os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"

    filename = task.partition(":")[2].strip()
    logger.info("Publishing '%s'...", filename)

    _pipeline_t0 = monotonic()
    run_log = None
    _current_stage = "init"

    try:
        pool = await get_pool()
        from pipeline.pipeline_logger import PipelineRunLogger, set_db_pool, mark_stale_runs_failed
        set_db_pool(pool)

        # Stale-run janitor — stale_after_hours=0 closes any unterminated run immediately.
        try:
            _stale = await mark_stale_runs_failed(pool, stale_after_hours=0)
            if _stale:
                logger.warning("Stale-run janitor: closed %d run(s): %s", len(_stale), ", ".join(_stale))
        except Exception as _jex:
            logger.warning("Stale-run janitor error (non-fatal): %s", _jex)

        run_log = PipelineRunLogger(topic=filename, command="PUBLISH")

        # ── Publish to Ghost ──
        _current_stage = "Publish"
        run_log.stage_start("Publish")
        _t0 = monotonic()
        publish_input = _build_publish_input(filename)
        publish_output, _, _ = await _run_agent_with_fallback(
            publisher, publish_input,
            agent_name="Publisher", pool=pool, max_turns=6, run_log=run_log,
        )

        # Title-length fix (same logic as _run_blog_pipeline)
        if publish_output.strip().startswith("MISSING:") and "title length" in publish_output.lower():
            research_dir_pub = _Path(__file__).parent.parent / "research"
            _fixed = await _fix_title_via_llm(_openai_client, research_dir_pub / filename)
            if _fixed:
                publish_input = _build_publish_input(filename)
                publish_output, _, _ = await _run_agent_with_fallback(
                    publisher, publish_input,
                    agent_name="Publisher", pool=pool, max_turns=6, run_log=run_log,
                )

        if publish_output.strip().startswith("MISSING:"):
            raise RuntimeError(
                f"Publish validation failed — fix the issue in the file and retry.\n"
                f"Unresolved: {publish_output}"
            )

        logger.info("Ghost result: %s", publish_output)
        run_log.stage_ok("Publish", elapsed_s=round(monotonic() - _t0, 1), url=publish_output)

        # ── LinkedIn ──
        _current_stage = "LinkedIn"
        run_log.stage_start("LinkedIn")
        _t0_li = monotonic()
        ghost_url, feature_image_url = _parse_publish_output(publish_output)
        if not ghost_url:
            _li_exc = RuntimeError(
                f"Could not parse Ghost URL from publisher output — LinkedIn blocked. "
                f"Output was: {publish_output[:200]}"
            )
            logger.error("LinkedIn: %s", _li_exc)
            run_log.stage_error("LinkedIn", _li_exc)
        else:
            research_dir = _Path(__file__).parent.parent / "research"
            edited_path = research_dir / filename
            if not edited_path.exists():
                logger.error("File not found for LinkedIn: %s", edited_path)
                run_log.stage_skipped("LinkedIn", f"file not found: {filename}")
            else:
                _li_result = ""
                _li_ok = False
                _li_skipped = False
                _li_delays = [10, 30]
                for _li_attempt in range(3):
                    if _li_attempt > 0:
                        _li_delay = _li_delays[_li_attempt - 1]
                        logger.info("LinkedIn: retry %d/3 after %ds...", _li_attempt + 1, _li_delay)
                        await asyncio.sleep(_li_delay)
                    _li_result = await _linkedin_post_direct(ghost_url, feature_image_url, edited_path)
                    if _li_result.startswith("SKIPPED:"):
                        _li_skipped = True
                        break
                    if "Error:" not in _li_result:
                        _li_ok = True
                        break
                    logger.warning("LinkedIn attempt %d/3 failed: %s", _li_attempt + 1, _li_result)

                if _li_skipped:
                    run_log.stage_skipped("LinkedIn", _li_result.replace("SKIPPED:", "").strip())
                    logger.info("LinkedIn skipped: %s", _li_result)
                elif _li_ok:
                    run_log.stage_ok("LinkedIn", elapsed_s=round(monotonic() - _t0_li, 1), result=_li_result)
                    logger.info("LinkedIn: %s", _li_result)
                else:
                    run_log.stage_error("LinkedIn", RuntimeError(_li_result))
                    logger.error("LinkedIn failed after 3 attempts: %s", _li_result)
                publish_output = f"{publish_output} | LinkedIn: {_li_result}"

        # ── Newsletter ──
        _current_stage = "Newsletter"
        run_log.stage_start("Newsletter")
        _t0_nl = monotonic()
        try:
            from pipeline.tools.newsletter import send_newsletter
            _nl_fm: dict = {}
            try:
                import re as _re_nl
                import yaml as _yaml_nl
                _nl_path = _Path(__file__).parent.parent / "research" / filename
                _raw_nl = _nl_path.read_text(encoding="utf-8")
                _fm_match = _re_nl.match(r"^---\s*\n(.*?)\n---", _raw_nl, _re_nl.DOTALL)
                if _fm_match:
                    _parsed = _yaml_nl.safe_load(_fm_match.group(1)) or {}
                    _nl_fm = {str(k).lower(): str(v).strip() if v is not None else "" for k, v in _parsed.items()}
                else:
                    for _k, _v in _re_nl.findall(r"^(\w+):\s*(.+)$", _raw_nl, _re_nl.MULTILINE):
                        _nl_fm[_k.lower()] = _v.strip()
            except Exception:
                pass
            _nl_title = _nl_fm.get("title", "")
            _nl_excerpt = _nl_fm.get("excerpt", "")
            newsletter_result = await send_newsletter(
                post_url=ghost_url,
                title=_nl_title or filename,
                excerpt=_nl_excerpt,
                feature_image_url=feature_image_url or "",
            )
        except Exception as _nl_exc:
            newsletter_result = f"Error: {_nl_exc}"
        if newsletter_result.startswith("SKIPPED:"):
            run_log.stage_skipped("Newsletter", newsletter_result.replace("SKIPPED:", "").strip())
            logger.info("Newsletter skipped: %s", newsletter_result)
        elif newsletter_result.startswith("Error:"):
            run_log.stage_error("Newsletter", RuntimeError(newsletter_result))
            logger.error("Newsletter failed: %s", newsletter_result)
        else:
            run_log.stage_ok("Newsletter", elapsed_s=round(monotonic() - _t0_nl, 1), result=newsletter_result)
            logger.info("Newsletter: %s", newsletter_result)
        publish_output = f"{publish_output} | Newsletter: {newsletter_result}"

        logger.info("Result: %s", publish_output)
        run_log.run_complete(published_url=publish_output, total_elapsed_s=round(monotonic() - _pipeline_t0, 1))
    except Exception as exc:
        _total = monotonic() - _pipeline_t0
        if run_log is not None:
            run_log.stage_error(_current_stage, exc)
            run_log.run_failed(_current_stage, exc, total_elapsed_s=_total)
        logger.error("PUBLISH pipeline failed: %s", exc, exc_info=True)
    finally:
        await asyncio.sleep(0.5)
        await close_pool()


async def _run_research_pipeline(task: str, debug: bool = False) -> dict:
    """Run RESEARCH or REPORT: Research + Index, no blog post.

    Returns a result dict with keys:
      - ``status``          — ``"complete"`` or ``"failed"``
      - ``index_result``    — chunk-count string from corpus indexing (complete only)
      - ``run_log``         — ``PipelineRunLogger`` instance
      - ``total_elapsed_s`` — wall-clock seconds
    """
    from pathlib import Path as _ResPath
    from pipeline.setup import init_github_models
    from pipeline.definitions import researcher
    from pipeline.db import get_pool, close_pool
    from pipeline.guardrails import log_model_call

    init_github_models()

    # Disable tracing — GitHub token is not a valid OpenAI key
    import os as _os
    _os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"

    prefix, _, topic = task.partition(":")
    topic = topic.strip()
    today_str = datetime.now().strftime("%Y-%m-%d")
    slug = "-".join(topic.lower().split()[:4]).replace(",", "").replace("'", "")
    research_dir = _ResPath(__file__).parent.parent / "research"
    research_dir.mkdir(exist_ok=True)
    research_cache_path = research_dir / f"{today_str}-{slug}-research.json"

    logger.info("Starting %s pipeline", prefix.strip().upper())
    logger.info("Topic: %s", topic)

    # Notify personal email that the pipeline has started
    _cmd_upper = prefix.strip().upper()
    _send_pipeline_notification(
        subject=f"[BeyondTomorrow] Starting {_cmd_upper}: {topic}",
        body=(
            f"Command  : {_cmd_upper}\n"
            f"Topic    : {topic}\n"
            f"Status   : Pipeline started\n"
            f"Started  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            f"Stages pending: Research → Index\n"
            f"You will receive a follow-up email when the pipeline completes."
        ),
    )


    _current_stage = "init"
    run_log = None
    _pipeline_result: dict = {"status": "failed", "run_log": None, "total_elapsed_s": 0.0}

    try:
        pool = await get_pool()
        from pipeline.pipeline_logger import PipelineRunLogger, set_db_pool, mark_stale_runs_failed
        set_db_pool(pool)

        # Stale-run janitor — close any stuck RUNNING runs before starting.
        try:
            _stale = await mark_stale_runs_failed(pool, stale_after_hours=0)
            if _stale:
                logger.warning(
                    "Stale-run janitor: closed %d orphaned run(s): %s",
                    len(_stale), ", ".join(_stale),
                )
        except Exception as _jex:
            logger.warning("Stale-run janitor error (non-fatal): %s", _jex)

        run_log = PipelineRunLogger(topic=topic, command=prefix.strip().upper())
        _pipeline_result["run_log"] = run_log

        # =============================================================
        # Step 1: Research
        # =============================================================
        _current_stage = "Research"
        run_log.stage_start("Research")
        _t0 = monotonic()

        if research_cache_path.exists():
            logger.info("Research cache found — loading from %s", research_cache_path.name)
            research_output = research_cache_path.read_text(encoding="utf-8")
        else:
            # RPM pacing — check before the Researcher's multi-turn tool calls
            try:
                from pipeline.guardrails import get_rpm_usage, RPM_LIMITS
                _res_model = researcher.model
                _res_rpm = await get_rpm_usage(pool, _res_model)
                _res_rpm_limit = RPM_LIMITS.get(_res_model, 10)
                if _res_rpm >= _res_rpm_limit - 2:
                    _res_cooldown = 45
                    logger.info(
                        "RPM pressure on %s (%d/%d) — cooling %ds before Research",
                        _res_model, _res_rpm, _res_rpm_limit, _res_cooldown,
                    )
                    await asyncio.sleep(_res_cooldown)
            except Exception:
                pass

            # Pre-fetch: seed the corpus before the LLM call
            logger.info("Pre-fetching pages into corpus before Researcher LLM call...")
            try:
                from pipeline.tools.search import _prefetch_topic
                await _prefetch_topic(topic, num_queries=2)
                logger.info("Pre-fetch complete.")
            except Exception as _pf_err:
                logger.warning("Pre-fetch failed (non-fatal): %s", _pf_err)

            research_input = (
                f"Research this topic thoroughly: {topic}\n\n"
                f"The knowledge corpus has already been seeded with pages on this topic.\n"
                f"REQUIRED STEPS:\n"
                f"1. Generate 2-3 search queries covering different angles.\n"
                f"2. For each query call search_and_index.\n"
                f"3. Call search_corpus ONCE with top_k=3 after indexing.\n"
                f"4. Return structured research JSON with key_findings, subtopics, "
                f"suggested_angles, gaps, source_list, total_sources, model_used."
            )
            research_output, r_tin, r_tout = await _run_agent_with_fallback(
                researcher, research_input,
                agent_name="Researcher", pool=pool, max_turns=8, run_log=run_log,
            )
            await log_model_call(pool, researcher.model, tokens_in=r_tin, tokens_out=r_tout, phase="research")
            logger.info("Research complete (tokens: in=%d out=%d)", r_tin, r_tout)

            # Strip hallucinated/dead source URLs before caching or indexing
            try:
                research_output = await _sanitise_research_sources(research_output)
            except Exception as _san_err:
                logger.warning("Source sanitisation failed (non-fatal): %s", _san_err)

            # Cache research JSON locally for retry resilience
            try:
                research_cache_path.write_text(research_output, encoding="utf-8")
                logger.info("Research JSON cached to %s", research_cache_path.name)
            except Exception as _cache_err:
                logger.warning("Could not cache research JSON: %s", _cache_err)

        run_log.stage_ok("Research", elapsed_s=round(monotonic() - _t0, 1), model=researcher.model)
        logger.info("Research done in %.1fs", monotonic() - _t0)

        # =============================================================
        # Step 2: Index to corpus
        # =============================================================
        _current_stage = "Index"
        run_log.stage_start("Index")
        _t0 = monotonic()

        # Bypass the Indexer agent — call _index_research_json directly to
        # avoid 413 Payload Too Large from the SDK request body.
        logger.info("Indexing research to corpus (direct)...")
        from pipeline.tools.corpus import _index_research_json
        index_output = await _index_research_json(
            research_json=research_output,
            source=f"{today_str}-{slug}-research",
            date=today_str,
        )

        _total = monotonic() - _pipeline_t0
        run_log.stage_ok("Index", elapsed_s=round(monotonic() - _t0, 1), detail=index_output)
        run_log.run_complete(published_url=index_output, total_elapsed_s=_total)
        logger.info("%s pipeline complete in %.1fs", prefix.strip().upper(), _total)
        logger.info("Corpus: %s", index_output)
        _pipeline_result = {
            "status": "complete",
            "index_result": index_output,
            "run_log": run_log,
            "total_elapsed_s": _total,
        }
        # Notify personal email: research/report pipeline succeeded
        _send_pipeline_notification(
            subject=f"[BeyondTomorrow] Complete: {prefix.strip().upper()}: {topic}",
            body=(
                f"Command  : {prefix.strip().upper()}\n"
                f"Topic    : {topic}\n"
                f"Status   : Complete\n"
                f"Result   : {index_output}\n"
                f"Duration : {int(_total // 60)}m {int(_total % 60)}s\n"
                f"\nStages:\n{_fmt_pipeline_stages(run_log)}"
            ),
        )

    except Exception as exc:
        _total = monotonic() - _pipeline_t0
        if run_log is not None:
            run_log.stage_error(_current_stage, exc)
            run_log.run_failed(_current_stage, exc, total_elapsed_s=_total)
        _pipeline_result = {
            "status": "failed",
            "run_log": run_log,
            "total_elapsed_s": _total,
        }
        logger.error(
            "%s pipeline failed at stage '%s': %s",
            prefix.strip().upper() if prefix.strip() else "Research",
            _current_stage, exc, exc_info=True,
        )
        # Notify personal email: research/report pipeline failed
        _send_pipeline_notification(
            subject=f"[BeyondTomorrow] FAILED: {prefix.strip().upper()}: {topic}",
            body=(
                f"Command  : {prefix.strip().upper()}\n"
                f"Topic    : {topic}\n"
                f"Status   : FAILED at {_current_stage}\n"
                f"Error    : {type(exc).__name__}: {exc}\n"
                f"Duration : {int(_total // 60)}m {int(_total % 60)}s\n"
                f"\nStages:\n{_fmt_pipeline_stages(run_log)}"
            ),
        )
    finally:
        await asyncio.sleep(0.5)
        await close_pool()

    return _pipeline_result


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
