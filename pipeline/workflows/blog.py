"""Blog workflow implementation."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from time import monotonic

from pipeline.paths import PROJECT_ROOT
from pipeline.workflows.common import _AGENT_TIMEOUT, _STAGE_COOLDOWN, _RETRY_BACKOFF_BASE

logger = logging.getLogger("pipeline")

from pipeline.workflows.evidence import _compact_research, _require_publish_evidence, _require_research_evidence, _sanitise_research_sources, _valid_research_cache
from pipeline.workflows.execution import _fix_title_via_llm, _run_agent_with_fallback
from pipeline.workflows.notifications import _fmt_pipeline_stages, _send_pipeline_notification
from pipeline.workflows.publishing import _build_publish_input, _linkedin_post_direct, _parse_publish_output


async def _run_blog_pipeline(task: str, debug: bool = False) -> dict:
    """Run the full BLOG pipeline: Research+Index → Write → Edit → Publish → Index."""
    from pathlib import Path

    from pipeline._sdk import Runner
    from pipeline.setup import init_openai
    from pipeline.definitions import researcher, writer, editor, publisher, indexer, model_settings_for
    from pipeline.db import get_pool, close_pool
    from pipeline.degradation import select_model

    _openai_client = init_openai()

    import os as _os
    _os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"

    topic = task.partition(":")[2].strip() if ":" in task else task
    research_dir = PROJECT_ROOT / "research"
    research_dir.mkdir(exist_ok=True)

    today_str = datetime.now().strftime("%Y-%m-%d")
    slug = "-".join(topic.lower().split()[:4]).replace(",", "").replace("'", "").replace(":", "")
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
    published_url = ""
    _pipeline_result: dict = {
        "status": "failed", "published_url": "", "run_log": None, "total_elapsed_s": 0.0
    }

    try:
        pool = await get_pool()
        from pipeline.pipeline_logger import PipelineRunLogger, set_db_pool, mark_stale_runs_failed
        set_db_pool(pool)

        # Stale-run janitor — close any stuck RUNNING runs before starting this one.
        # Only close runs older than the recovery threshold, never every active run.
        # Safe because the new run_start is logged AFTER this call.
        try:
            _stale = await mark_stale_runs_failed(pool, stale_after_hours=2)
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

        if research_cache_path.exists() and _valid_research_cache(research_cache_path, require_evidence=True):
            logger.info("Research cache found — loading from %s", research_cache_path.name)
            research_output = research_cache_path.read_text(encoding="utf-8")
        elif (research_dir / draft_filename).exists() or (research_dir / edited_filename).exists():
            raise RuntimeError("Existing draft lacks research meeting the current evidence policy; retain it for review before publishing")
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

            from pipeline.source_policy import source_guidance
            research_input = (
                f"Research this topic thoroughly for a blog post: {topic}\n\n"
                f"The knowledge corpus has already been seeded with pages on this topic.\n"
                f"REQUIRED STEPS:\n"
                f"1. Generate 2-3 targeted search queries covering different angles.\n"
                f"2. For each query call search_and_index to fetch and store any new pages.\n"
                f"3. Call search_corpus TWICE with top_k=3: main topic, then a contrasting angle.\n"
                f"4. Return structured research JSON with key_findings, subtopics, "
                f"suggested_angles, gaps, source_list, total_sources, model_used, "
                f"question_coverage, ready_to_write. Choose topic-relevant pages from approved "
                f"sources. One relevant approved source supporting a useful finding is enough; "
                f"aim for two independent publishers when available. Disclose partial or "
                f"unanswered questions in gaps and limit the article to supported findings. "
                f"Incomplete coverage must not veto a useful, clearly scoped article.\n\n"
                f"Topic-specific source candidates:\n{source_guidance(topic)}"
            )
            research_output, r_tin, r_tout = await _run_agent_with_fallback(
                researcher, research_input,
                agent_name="Researcher", pool=pool, max_turns=8, run_log=run_log,
            )
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

        # Keep only supported findings and carry evidence gaps into drafting.
        # The original output is already cached above for diagnosis on failure.
        research_output = _require_research_evidence(research_output)
        try:
            research_cache_path.write_text(research_output, encoding="utf-8")
        except OSError as _cache_err:
            logger.warning("Could not update scoped research cache: %s", _cache_err)

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
        # Preserve claim/source pairs and uncertainty for the fact-check pass.
        research_compact_editor = _compact_research(research_output, max_chars=8000)

        if (research_dir / draft_filename).exists():
            logger.info("Draft already exists, skipping writer: %s", draft_filename)
        else:
            _require_research_evidence(research_output)
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
        _require_publish_evidence(research_dir / edited_filename, research_output)
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

        # --- Handle MISSING: validation failures from publish_file_to_ghost ---
        if publish_output.strip().startswith("MISSING:"):
            logger.warning("Publish blocked — pre-publish validation failed: %s", publish_output)
            missing_lower = publish_output.lower()

            # Title-length failure: fix with a single ~30-token LLM call.
            # No need to load the full post — the existing title is all the model needs.
            if "title length" in missing_lower:
                _fixed = await _fix_title_via_llm(_openai_client, research_dir / edited_filename, pool=pool, run_log=run_log)
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

            logger.info("Retrying Publisher after recovery...")
            publish_output, pr_tin, pr_tout = await _run_agent_with_fallback(
                publisher, publish_input,
                agent_name="Publisher", pool=pool, max_turns=6, run_log=run_log,
            )

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

        from pipeline.workflows.publishing import confirmed_publication
        published = await confirmed_publication(edited_filename)
        published_url = published['url']
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
        ghost_url, feature_image_url = published['url'], published.get('feature_image', '')
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
        if str(index_output).startswith(('Error:', 'Failed', 'Skipped')):
            run_log.stage_error('Index', RuntimeError(str(index_output)))
        else:
            run_log.stage_ok("Index", elapsed_s=round(monotonic() - _t0, 1), detail=index_output)
        logger.info("[5/5] Index done in %.1fs", monotonic() - _t0)
        logger.info("BLOG pipeline complete in %.1fs (%.1f min)", _total, _total / 60)
        logger.info("Published: %s", publish_output)
        logger.info("Corpus: %s", index_output)
        run_log.run_complete(published_url=publish_output, total_elapsed_s=_total)
        from pipeline.workflows.results import failed_stages
        incomplete = failed_stages(run_log)
        _pipeline_result = {
            "status": "partial" if incomplete else "published",
            "published_url": published_url,
            "ghost_post_id": published["id"],
            "failed_stages": incomplete,
            "run_log": run_log,
            "total_elapsed_s": _total,
        }
        # Notify personal email: pipeline succeeded
        _mins = _total / 60
        _send_pipeline_notification(
            subject=f"[BeyondTomorrow] {'Partial' if incomplete else 'Published'}: {topic}",
            body=(
                f"Command  : BLOG\n"
                f"Topic    : {topic}\n"
                f"Status   : {'Partially complete' if incomplete else 'Published'}\n"
                f"URL      : {publish_output}\n"
                f"Duration : {int(_total // 60)}m {int(_total % 60)}s\n"
                f"\nStages:\n{_fmt_pipeline_stages(run_log)}"
            ),
        )
    except Exception as exc:
        _total = monotonic() - _pipeline_t0
        if not published_url and _current_stage == 'Publish':
            try:
                from pipeline.workflows.publishing import confirmed_publication
                published_url = (await confirmed_publication(edited_filename))['url']
            except Exception:
                pass  # No confirmed receipt; do not claim that Ghost published.
        if run_log is not None:
            run_log.stage_error(_current_stage, exc)
            run_log.run_failed(_current_stage, exc, total_elapsed_s=_total)
        _pipeline_result = {
            "status": "partial" if published_url else "failed",
            "published_url": published_url,
            "failed_stages": [_current_stage],
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
