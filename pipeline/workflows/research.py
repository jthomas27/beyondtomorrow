"""Research workflow implementation."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from time import monotonic

from pipeline.paths import PROJECT_ROOT
from pipeline.workflows.common import _AGENT_TIMEOUT, _STAGE_COOLDOWN, _RETRY_BACKOFF_BASE

logger = logging.getLogger("pipeline")

from pipeline.workflows.evidence import _sanitise_research_sources, _valid_research_cache
from pipeline.workflows.execution import _run_agent_with_fallback
from pipeline.workflows.notifications import _fmt_pipeline_stages, _send_pipeline_notification


async def _run_research_pipeline(task: str, debug: bool = False) -> dict:
    """Run RESEARCH or REPORT: Research + Index, no blog post.

    Returns a result dict with keys:
      - ``status``          — ``"complete"`` or ``"failed"``
      - ``index_result``    — chunk-count string from corpus indexing (complete only)
      - ``run_log``         — ``PipelineRunLogger`` instance
      - ``total_elapsed_s`` — wall-clock seconds
    """
    from pathlib import Path as _ResPath
    from pipeline.setup import init_openai
    from pipeline.definitions import researcher
    from pipeline.db import get_pool, close_pool

    init_openai()

    import os as _os
    _os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"

    prefix, _, topic = task.partition(":")
    topic = topic.strip()
    today_str = datetime.now().strftime("%Y-%m-%d")
    slug = "-".join(topic.lower().split()[:4]).replace(",", "").replace("'", "").replace(":", "")
    research_dir = PROJECT_ROOT / "research"
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


    _pipeline_t0 = monotonic()
    _current_stage = "init"
    run_log = None
    _pipeline_result: dict = {"status": "failed", "run_log": None, "total_elapsed_s": 0.0}

    try:
        pool = await get_pool()
        from pipeline.pipeline_logger import PipelineRunLogger, set_db_pool, mark_stale_runs_failed
        set_db_pool(pool)

        # Stale-run janitor — close any stuck RUNNING runs before starting.
        try:
            _stale = await mark_stale_runs_failed(pool, stale_after_hours=2)
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

        if research_cache_path.exists() and _valid_research_cache(research_cache_path):
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

            from pipeline.source_policy import source_guidance
            research_input = (
                f"Research this topic thoroughly: {topic}\n\n"
                f"The knowledge corpus has already been seeded with pages on this topic.\n"
                f"REQUIRED STEPS:\n"
                f"1. Generate 2-3 search queries covering different angles.\n"
                f"2. For each query call search_and_index.\n"
                f"3. Call search_corpus TWICE with top_k=3: main topic, then a contrasting angle.\n"
                f"4. Return structured research JSON with key_findings, subtopics, "
                f"suggested_angles, gaps, source_list, total_sources, model_used, "
                f"question_coverage, ready_to_write.\n\n"
                f"Topic-specific source candidates:\n{source_guidance(topic)}"
            )
            research_output, r_tin, r_tout = await _run_agent_with_fallback(
                researcher, research_input,
                agent_name="Researcher", pool=pool, max_turns=8, run_log=run_log,
            )
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
