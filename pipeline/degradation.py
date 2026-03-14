"""
pipeline/degradation.py — Automatic model fallback selection.

Selects the best available model from the fallback chain by checking each
model's daily budget status via the guardrails module. Falls back to cheaper
models when the preferred one is at or near its rate limit.

Usage::

    from pipeline.degradation import select_model

    model = await select_model("openai/gpt-5", pool=pool)
    # Returns "openai/gpt-4.1" if gpt-5 is exhausted, etc.
"""

from typing import Optional

from pipeline.guardrails import check_model_budget

# ---------------------------------------------------------------------------
# Fallback chain — ordered from most capable to most available.
# When a model is exhausted the agent steps forward to the next entry.
# ---------------------------------------------------------------------------

FALLBACK_CHAIN: list[str] = [
    "openai/gpt-5",
    "openai/gpt-4.1",
    "openai/gpt-5-mini",
    "openai/gpt-4.1-mini",
    "openai/gpt-4.1-nano",
]


def get_fallback(model: str) -> Optional[str]:
    """Return the next model in the fallback chain after *model*.

    Returns ``None`` if *model* is already the last entry or if the chain
    is exhausted. For unknown models (not in the chain), returns the first
    chain entry.

    Args:
        model: Current model identifier string.
    """
    try:
        idx = FALLBACK_CHAIN.index(model)
    except ValueError:
        # Unknown model — direct to the start of the chain
        return FALLBACK_CHAIN[0] if FALLBACK_CHAIN else None

    next_idx = idx + 1
    return FALLBACK_CHAIN[next_idx] if next_idx < len(FALLBACK_CHAIN) else None


async def select_model(preferred_model: str, pool=None) -> str:
    """Select the best available model, falling back if budget is exhausted.

    Walks the fallback chain starting at *preferred_model* and returns the
    first model whose budget check passes. If every model is exhausted,
    returns the last model in the chain (last resort).

    Args:
        preferred_model: The model you'd ideally like to use.
        pool: asyncpg connection pool. If ``None``, skips DB checks and
              returns *preferred_model* unchanged (useful for dry-run / tests
              that do not need a real DB).

    Returns:
        Model name string — always returns a non-empty string.
    """
    if pool is None:
        return preferred_model

    # Build an ordered list starting at preferred_model's position in chain.
    try:
        start_idx = FALLBACK_CHAIN.index(preferred_model)
    except ValueError:
        start_idx = 0

    candidates = FALLBACK_CHAIN[start_idx:]

    for model in candidates:
        status = await check_model_budget(pool, model)
        if status["available"]:
            return model

    # All candidates exhausted — return last resort.
    return FALLBACK_CHAIN[-1]
