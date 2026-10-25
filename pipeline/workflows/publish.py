"""Publish workflow implementation."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from time import monotonic

from pipeline.paths import PROJECT_ROOT
from pipeline.workflows.common import _AGENT_TIMEOUT, _STAGE_COOLDOWN, _RETRY_BACKOFF_BASE

logger = logging.getLogger("pipeline")

from pipeline.workflows.evidence import _require_publish_evidence
from pipeline.workflows.execution import _fix_title_via_llm, _run_agent_with_fallback
from pipeline.workflows.publishing import _build_publish_input, _linkedin_post_direct, _parse_publish_output


async def _run_publish_only(task: str, debug: bool = False) -> dict:
    """Run only the Publisher step for an already-edited file.

    Usage:  python -m pipeline.main "PUBLISH: 2026-03-13-my-post-edited.md"
    """
    from pipeline.setup import init_openai
    from pipeline.definitions import publisher
    from pipeline.db import get_pool, close_pool
    from pathlib import Path as _Path

    _openai_client = init_openai()

    import os as _os
    _os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"

    filename = task.partition(":")[2].strip()
    logger.info("Publishing '%s'...", filename)

    _pipeline_t0 = monotonic()
    run_log = None
    ghost_url = ""
    result = {"status": "failed", "published_url": ""}
    _current_stage = "init"

    try:
        pool = await get_pool()
        from pipeline.pipeline_logger import PipelineRunLogger, set_db_pool, mark_stale_runs_failed
        set_db_pool(pool)

        # Stale-run janitor — use an age threshold to preserve concurrent active runs.
        try:
            _stale = await mark_stale_runs_failed(pool, stale_after_hours=2)
            if _stale:
                logger.warning("Stale-run janitor: closed %d run(s): %s", len(_stale), ", ".join(_stale))
        except Exception as _jex:
            logger.warning("Stale-run janitor error (non-fatal): %s", _jex)

        run_log = PipelineRunLogger(topic=filename, command="PUBLISH")

        # ── Publish to Ghost ──
        _current_stage = "Publish"
        run_log.stage_start("Publish")
        _t0 = monotonic()
        _require_publish_evidence(PROJECT_ROOT / "research" / filename)
        publish_input = _build_publish_input(filename)
        publish_output, _, _ = await _run_agent_with_fallback(
            publisher, publish_input,
            agent_name="Publisher", pool=pool, max_turns=6, run_log=run_log,
        )

        # Title-length fix (same logic as _run_blog_pipeline)
        if publish_output.strip().startswith("MISSING:") and "title length" in publish_output.lower():
            research_dir_pub = PROJECT_ROOT / "research"
            _fixed = await _fix_title_via_llm(_openai_client, research_dir_pub / filename, pool=pool, run_log=run_log)
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

        from pipeline.workflows.publishing import confirmed_publication
        published = await confirmed_publication(filename)
        ghost_url, feature_image_url = published['url'], published.get('feature_image', '')
        logger.info("Ghost result: %s", publish_output)
        run_log.stage_ok("Publish", elapsed_s=round(monotonic() - _t0, 1), url=publish_output)

        # ── LinkedIn ──
        _current_stage = "LinkedIn"
        run_log.stage_start("LinkedIn")
        _t0_li = monotonic()
        ghost_url, feature_image_url = published['url'], published.get('feature_image', '')
        if not ghost_url:
            _li_exc = RuntimeError(
                f"Could not parse Ghost URL from publisher output — LinkedIn blocked. "
                f"Output was: {publish_output[:200]}"
            )
            logger.error("LinkedIn: %s", _li_exc)
            run_log.stage_error("LinkedIn", _li_exc)
        else:
            research_dir = PROJECT_ROOT / "research"
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
                _nl_path = PROJECT_ROOT / "research" / filename
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
        run_log.run_complete(published_url=ghost_url, total_elapsed_s=round(monotonic() - _pipeline_t0, 1))
        from pipeline.workflows.results import failed_stages
        incomplete = failed_stages(run_log)
        result = {'status': 'partial' if incomplete else 'published', 'published_url': ghost_url,
                  'ghost_post_id': published['id'], 'failed_stages': incomplete, 'run_log': run_log}
    except Exception as exc:
        _total = monotonic() - _pipeline_t0
        if not ghost_url and _current_stage == 'Publish':
            try:
                from pipeline.workflows.publishing import confirmed_publication
                ghost_url = (await confirmed_publication(filename))['url']
            except Exception:
                pass
        if run_log is not None:
            run_log.stage_error(_current_stage, exc)
            run_log.run_failed(_current_stage, exc, total_elapsed_s=_total)
        result = {'status': 'partial' if ghost_url else 'failed', 'published_url': ghost_url,
                  'failed_stages': [_current_stage], 'run_log': run_log}
        logger.error("PUBLISH pipeline failed: %s", exc, exc_info=True)
    finally:
        await asyncio.sleep(0.5)
        await close_pool()

    return result
