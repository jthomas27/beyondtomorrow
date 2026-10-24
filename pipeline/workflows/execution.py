"""Execution workflow implementation."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from time import monotonic

from pipeline.paths import PROJECT_ROOT
from pipeline.workflows.common import _AGENT_TIMEOUT, _STAGE_COOLDOWN, _RETRY_BACKOFF_BASE

logger = logging.getLogger("pipeline")



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
            return False  # request-schema bugs must fail immediately, not burn retries
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
    from pipeline.degradation import get_fallback, select_model, ModelBudgetExceeded
    from pipeline.config_loader import get_models
    from pipeline.model_usage import ModelUsageHooks

    cfg = get_models()["agents"].get(agent_name.lower(), {})
    allow_fallback = cfg.get("allow_fallback", agent_name.lower() not in {"researcher", "writer", "editor"})
    if agent_name.lower() == "publisher":
        # A completed Ghost tool call followed by a model timeout must not be replayed.
        max_attempts = 1
    usage_hooks = ModelUsageHooks(pool, run_log=run_log)

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
        selected = await select_model(current_model, pool=pool, allow_fallback=allow_fallback)
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
    except ModelBudgetExceeded:
        # A daily hard limit must not be swallowed. Short RPM pressure can clear.
        budget = await check_model_budget(pool, current_model)
        if not budget.get("rpm_exceeded") or budget.get("pct", 0) >= 95:
            raise
        wait_s = await get_rpm_clear_wait(pool, current_model, max_wait=90)
        if wait_s >= 90:
            raise
        await asyncio.sleep(wait_s)
        await select_model(current_model, pool=pool, allow_fallback=allow_fallback)
    except Exception as sel_err:
        logger.warning("%s: select_model failed (non-fatal): %s", agent_name, sel_err)

    try:
        last_exc: Exception | None = None
        for attempt in range(max_attempts):
            try:
                result = await asyncio.wait_for(
                    Runner.run(agent, max_turns=max_turns, input=input_text, hooks=usage_hooks),
                    timeout=_AGENT_TIMEOUT,
                )
                tokens_in, tokens_out = _extract_usage(result)
                output = result.final_output
                if agent_name.lower() == "researcher":
                    # Model identity is execution metadata, not a fact for the LLM to infer.
                    import json
                    try:
                        research = json.loads(output)
                        if isinstance(research, dict):
                            research["model_used"] = current_model
                            output = json.dumps(research, ensure_ascii=False)
                    except (ValueError, TypeError) as exc:
                        # Do not cache or index a token-truncated JSON response as successful research.
                        raise RuntimeError("Research returned incomplete or invalid JSON; defer before caching") from exc
                    if not isinstance(research, dict):
                        raise RuntimeError("Research must return a JSON object; defer before caching")
                return output, tokens_in, tokens_out
            except asyncio.TimeoutError:
                logger.warning(
                    "%s timed out after %ds (attempt %d/%d)",
                    agent_name, _AGENT_TIMEOUT, attempt + 1, max_attempts,
                )
                if attempt + 1 >= max_attempts:
                    raise
                # First timeout: retry same model; subsequent: fall back
                if attempt > 0:
                    fallback = get_fallback(current_model, allow_fallback=allow_fallback)
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
                            from dataclasses import replace
                            agent.model_settings = replace(agent.model_settings, max_tokens=reduced_mt)
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
                    fallback = get_fallback(current_model, allow_fallback=allow_fallback)
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
                    elif attempt + 1 < max_attempts:
                        backoff = min(_RETRY_BACKOFF_BASE * (2 ** attempt), 300)
                        logger.info("%s: retrying %s in %ds without quality downgrade", agent_name, current_model, backoff)
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

async def _fix_title_via_llm(openai_client, edited_path, *, pool=None, run_log=None) -> bool:
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
        from pipeline.config_loader import get_models
        from pipeline.definitions import model_settings_for
        model = get_models()["agents"].get("title_repair", {}).get("model", "gpt-6-luna")
        settings = model_settings_for("title_repair", default_tokens=64)
        from pipeline.model_usage import ModelUsageHooks
        from types import SimpleNamespace
        hooks = ModelUsageHooks(pool, run_log=run_log)
        title_agent = SimpleNamespace(name="TitleRepair", model=model)
        await hooks.on_llm_start(None, title_agent, None, [])
        resp = await openai_client.responses.create(
            model=model,
            max_output_tokens=settings.max_tokens,
            reasoning=settings.reasoning,
            temperature=settings.temperature,
            input=[
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
        if getattr(resp, "usage", None):
            await hooks.on_llm_end(None, title_agent, resp)
        if getattr(resp, "status", "completed") != "completed":
            return False
        new_title = resp.output_text.strip().strip('"').strip("'")
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
