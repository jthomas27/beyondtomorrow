"""
pipeline/guardrails.py — Rate-limit guardrails for GitHub Models API.

Checks the ``rate_limit_log`` table to see how many calls each model has
consumed today, then blocks (hard threshold) or warns (soft threshold)
before making further API calls.

The ``rate_limit_log`` table schema::

    CREATE TABLE rate_limit_log (
        id            SERIAL PRIMARY KEY,
        agent_name    VARCHAR NOT NULL DEFAULT '',
        model         VARCHAR,
        tokens_input  INTEGER NOT NULL DEFAULT 0,
        tokens_output INTEGER NOT NULL DEFAULT 0,
        request_type  VARCHAR NOT NULL DEFAULT 'chat',
        session_id    VARCHAR,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
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


async def get_rpm_clear_wait(pool, model: str, max_wait: int = 90) -> int:
    """Return the seconds to wait until the RPM window has capacity again.

    Queries the oldest call in the last 60 seconds for *model* and returns
    how many seconds remain until it falls off the rolling window.

    Returns:
        0 — RPM window already has capacity (no wait needed).
        1–max_wait — seconds to wait before retrying the preferred model.
        max_wait — window won't clear within *max_wait* seconds; caller
                   should fall back to the next model rather than waiting.
    """
    limit = RPM_LIMITS.get(model, 0)
    if limit == 0:
        return 0  # no RPM tracking for this model

    used = await get_rpm_usage(pool, model)
    if used < limit:
        return 0  # already under limit — no wait needed

    # Find the oldest call within the 60s window so we know when a slot opens
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=60)
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT MIN(created_at) AS oldest FROM rate_limit_log "
                "WHERE model = $1 AND created_at >= $2",
                model, cutoff,
            )
        if row and row["oldest"]:
            oldest = row["oldest"]
            # Make timezone-aware if needed
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=timezone.utc)
            slot_opens_in = 60.0 - (datetime.now(timezone.utc) - oldest).total_seconds()
            wait = max(1, int(slot_opens_in) + 2)  # +2s buffer
            return min(wait, max_wait)
    except Exception:
        pass

    return max_wait  # safe default — let caller decide whether to wait or fall back


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


# ---------------------------------------------------------------------------
# Readability metrics (no external dependencies)
# ---------------------------------------------------------------------------

import logging as _logging
import re as _re

_guardrails_logger = _logging.getLogger("pipeline.guardrails")


def _count_syllables(word: str) -> int:
    """Estimate syllable count for an English word (heuristic)."""
    word = word.lower().strip(".,;:!?\"'""''")
    if not word:
        return 0
    if len(word) <= 3:
        return 1
    # Count vowel groups
    count = len(_re.findall(r"[aeiouy]+", word))
    # Silent e at end
    if word.endswith("e") and not word.endswith("le"):
        count = max(count - 1, 1)
    return max(count, 1)


def score_readability(text: str) -> dict:
    """Compute readability metrics for a blog post.

    Returns a dict with:
        word_count       — total words (excluding frontmatter)
        sentence_count   — number of sentences
        avg_sentence_len — average words per sentence
        flesch_score      — Flesch Reading Ease (0–100; higher = easier)
        grade_label       — human-readable grade label
        warnings         — list of warning strings for out-of-range values

    Target ranges for BeyondTomorrow.World:
        Word count:        1200–1800
        Avg sentence len:  12–22 words
        Flesch score:      50–70 (accessible but not dumbed-down)
    """
    # Strip YAML frontmatter
    stripped = _re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, count=1, flags=_re.DOTALL)
    # Strip markdown headings, links, images for cleaner word count
    stripped = _re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", stripped)
    stripped = _re.sub(r"^#{1,6}\s+", "", stripped, flags=_re.MULTILINE)
    # Strip bold/italic markers
    stripped = _re.sub(r"\*{1,3}|_{1,3}", "", stripped)

    words = stripped.split()
    word_count = len(words)

    # Split into sentences (approximation)
    sentences = _re.split(r"[.!?]+(?:\s|$)", stripped)
    sentences = [s.strip() for s in sentences if s.strip()]
    sentence_count = max(len(sentences), 1)

    avg_sentence_len = round(word_count / sentence_count, 1)

    # Flesch Reading Ease
    total_syllables = sum(_count_syllables(w) for w in words)
    if word_count > 0:
        flesch = (
            206.835
            - 1.015 * (word_count / sentence_count)
            - 84.6 * (total_syllables / word_count)
        )
        flesch = round(flesch, 1)
    else:
        flesch = 0.0

    # Grade label
    if flesch >= 70:
        grade_label = "Easy (general public)"
    elif flesch >= 50:
        grade_label = "Moderate (engaged reader)"
    elif flesch >= 30:
        grade_label = "Difficult (specialist)"
    else:
        grade_label = "Very difficult (academic)"

    warnings: list[str] = []
    if word_count < 1200:
        warnings.append(f"Word count ({word_count}) is below target minimum of 1200")
    elif word_count > 1800:
        warnings.append(f"Word count ({word_count}) exceeds target maximum of 1800")
    if avg_sentence_len > 22:
        warnings.append(f"Average sentence length ({avg_sentence_len} words) is high — aim for ≤22")
    if flesch < 50:
        warnings.append(f"Flesch score ({flesch}) is low — text may be too dense for target audience")

    return {
        "word_count": word_count,
        "sentence_count": sentence_count,
        "avg_sentence_len": avg_sentence_len,
        "flesch_score": flesch,
        "grade_label": grade_label,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# Cross-post reference guardrail
# ---------------------------------------------------------------------------

# Patterns that indicate a reference to a previous/other blog post on the site.
# These are banned from published content — each post must stand on its own.
_CROSS_POST_REF_RE = _re.compile(
    r"check\s+out\s+(?:our|my|this|the)?\s*(?:article|post|piece|story|blog|previous)"
    r"|read\s+(?:our|my|this|the)\s+(?:previous|earlier|related|recent|other)\s+(?:article|post|piece|blog)"
    r"|in\s+(?:our|my)\s+(?:previous|earlier|related|recent|other)\s+(?:article|post|piece|blog)"
    r"|as\s+(?:we|I)\s+(?:explored|covered|discussed|wrote|explained)\s+in\s+(?:our|my|this|the|a\s+previous)"
    r"|see\s+(?:our|my|this|the)\s+(?:previous|earlier|related|recent|other)\s+(?:article|post|piece|blog)"
    r"|(?:for\s+a\s+deeper\s+dive|for\s+more\s+(?:on|about|info|information)|learn\s+more)[^.!?\n]*(?:check\s+out|see\s+our|read\s+our)",
    _re.IGNORECASE,
)


def strip_cross_post_references(text: str) -> tuple[str, list[str]]:
    """Remove lines that reference other blog posts on the site.

    Posts must stand alone — cross-references to earlier articles break the
    reader experience and reveal the automated pipeline's internal structure.

    Scans the content line-by-line and removes any line matching
    :data:`_CROSS_POST_REF_RE`.  Collapses any resulting triple-blank-line
    gaps left by the removal.

    Returns:
        (cleaned_text, stripped_lines) — the sanitised content and a list of
        the removed lines (for logging).
    """
    stripped: list[str] = []
    clean_lines: list[str] = []
    for line in text.split("\n"):
        if _CROSS_POST_REF_RE.search(line):
            stripped.append(line.strip())
            _guardrails_logger.warning("Cross-post reference stripped: %r", line.strip())
        else:
            clean_lines.append(line)

    cleaned = "\n".join(clean_lines)
    # Collapse any triple+ blank lines left by the removal
    cleaned = _re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, stripped
