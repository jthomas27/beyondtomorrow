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

from datetime import date, datetime, timedelta, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Daily budget limits (GitHub Models API, Copilot Pro+ tier)
# Pro+ has unlimited premium requests but per-minute RPM/TPM limits still
# apply.  Daily limits here act as a safety net for degradation routing.
# ---------------------------------------------------------------------------

DAILY_LIMITS: dict[str, int] = {
    "openai/gpt-4.1": 80,       # Primary model — high tier
    "openai/gpt-4.1-mini": 500, # Fast fallback — generous limits
    "openai/gpt-4.1-nano": 500, # Last-resort budget tier
    "openai/gpt-5": 80,         # Available but not in primary chain
    "openai/gpt-5-mini": 500,
    "openai/gpt-5-nano": 500,
    "openai/gpt-4o": 80,
}

# Per-minute request limits — mirrors GitHub Models per-minute RPM windows.
# Used by check_rpm() to proactively throttle before hitting 429s.
RPM_LIMITS: dict[str, int] = {
    "openai/gpt-4.1": 10,
    "openai/gpt-4.1-mini": 30,
    "openai/gpt-4.1-nano": 30,
    "openai/gpt-5": 10,
    "openai/gpt-5-mini": 30,
    "openai/gpt-5-nano": 30,
    "openai/gpt-4o": 10,
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


async def get_rpm_usage(pool, model: str) -> int:
    """Return the number of API calls for *model* in the last 60 seconds."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM rate_limit_log "
            "WHERE model = $1 AND created_at >= $2",
            model,
            cutoff,
        )
    return int(row["cnt"]) if row else 0


async def check_rpm(pool, model: str) -> dict:
    """Check whether a model is within its per-minute request limit.

    Returns::

        {
            "ok":      bool,   # True if under the RPM limit
            "used":    int,    # Calls in the last 60 seconds
            "limit":   int,    # Per-minute limit for this model
            "model":   str,
        }
    """
    limit = RPM_LIMITS.get(model, 0)
    if limit == 0:
        return {"ok": True, "used": 0, "limit": 0, "model": model}

    used = await get_rpm_usage(pool, model)
    return {
        "ok": used < limit,
        "used": used,
        "limit": limit,
        "model": model,
    }


async def check_model_budget(pool, model: str) -> dict:
    """Check whether a model is available for another API call.

    Returns a status dict::

        {
            "available": bool,   # False if usage >= hard threshold OR RPM exceeded
            "warning":   bool,   # True if usage >= soft threshold
            "pct":       float,  # Percentage of daily limit used (0–100)
            "used":      int,    # Calls made today
            "limit":     int,    # Daily call limit for this model
            "rpm_exceeded": bool,  # True if per-minute limit hit
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
            "rpm_exceeded": False,
            "model": model,
        }

    used = await get_daily_usage(pool, model)
    pct = (used / limit) * 100.0

    rpm_status = await check_rpm(pool, model)
    rpm_exceeded = not rpm_status["ok"]

    return {
        "available": pct < HARD_THRESHOLD_PCT and not rpm_exceeded,
        "warning": pct >= SOFT_THRESHOLD_PCT,
        "pct": round(pct, 1),
        "used": used,
        "limit": limit,
        "rpm_exceeded": rpm_exceeded,
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
    agent_name = phase or "unknown"
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO rate_limit_log "
            "(agent_name, model, tokens_input, tokens_output, session_id, request_type) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            agent_name,
            model,
            tokens_in,
            tokens_out,
            run_id,
            agent_name,
        )
