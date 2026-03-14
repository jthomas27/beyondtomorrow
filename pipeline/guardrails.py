"""
pipeline/guardrails.py — Rate-limit guardrails for GitHub Models API.

Checks the ``rate_limit_log`` table to see how many calls each model has
consumed today, then blocks (hard threshold) or warns (soft threshold)
before making further API calls.

The ``rate_limit_log`` table schema::

    CREATE TABLE rate_limit_log (
        id         SERIAL PRIMARY KEY,
        model      TEXT NOT NULL,
        tokens_in  INTEGER NOT NULL DEFAULT 0,
        tokens_out INTEGER NOT NULL DEFAULT 0,
        run_id     TEXT,
        phase      TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
"""

from datetime import date
from typing import Optional

# ---------------------------------------------------------------------------
# Daily budget limits (GitHub Models API, Copilot Pro+ tier)
# Pro+ has unlimited premium requests — no daily caps.
# These limits are set high as a safety net; not expected to be hit.
# ---------------------------------------------------------------------------

DAILY_LIMITS: dict[str, int] = {
    "openai/gpt-5": 9999,
    "openai/gpt-5-mini": 9999,
    "openai/gpt-5-nano": 9999,
    "openai/gpt-4.1": 9999,
    "openai/gpt-4o": 9999,
    "openai/gpt-4.1-mini": 9999,
    "openai/gpt-4.1-nano": 9999,
}

# Percentage thresholds for soft warning vs. hard block.
SOFT_THRESHOLD_PCT: float = 80.0
HARD_THRESHOLD_PCT: float = 95.0


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

async def get_daily_usage(pool, model: str) -> int:
    """Return the number of API calls logged for *model* today (UTC date).

    Queries the ``rate_limit_log`` table. Returns 0 if no records exist.
    """
    today = date.today()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM rate_limit_log "
            "WHERE model = $1 AND created_at::date = $2",
            model,
            today,
        )
    return int(row["cnt"]) if row else 0


async def check_model_budget(pool, model: str) -> dict:
    """Check whether a model is available for another API call.

    Returns a status dict::

        {
            "available": bool,   # False if usage >= hard threshold
            "warning":   bool,   # True if usage >= soft threshold
            "pct":       float,  # Percentage of daily limit used (0–100)
            "used":      int,    # Calls made today
            "limit":     int,    # Daily call limit for this model
            "model":     str,
        }

    If the model is unknown (not in :data:`DAILY_LIMITS`), it is always
    available (no budget applies).
    """
    limit = DAILY_LIMITS.get(model, 0)
    if limit == 0:
        return {
            "available": True,
            "warning": False,
            "pct": 0.0,
            "used": 0,
            "limit": 0,
            "model": model,
        }

    used = await get_daily_usage(pool, model)
    pct = (used / limit) * 100.0

    return {
        "available": pct < HARD_THRESHOLD_PCT,
        "warning": pct >= SOFT_THRESHOLD_PCT,
        "pct": round(pct, 1),
        "used": used,
        "limit": limit,
        "model": model,
    }


async def log_model_call(
    pool,
    model: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    run_id: Optional[str] = None,
    phase: str = "",
) -> None:
    """Insert one record into ``rate_limit_log`` for an API call."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO rate_limit_log "
            "(agent_name, model, tokens_input, tokens_output, session_id, request_type) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            phase or "unknown",
            model,
            tokens_in,
            tokens_out,
            run_id,
            phase,
        )
