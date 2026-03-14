"""
tests/test_guardrails.py — Unit tests for pipeline/guardrails.py

Covers:
    get_daily_usage       — queries rate_limit_log and returns integer count
    check_model_budget    — returns correct available/warning flags and pct
                            at various usage levels; handles unknown models
    log_model_call        — inserts one row into rate_limit_log with correct args

DB calls are mocked via pytest-mock fixtures from conftest.py.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from pipeline.guardrails import (
    DAILY_LIMITS,
    HARD_THRESHOLD_PCT,
    SOFT_THRESHOLD_PCT,
    check_model_budget,
    get_daily_usage,
    log_model_call,
)


# ---------------------------------------------------------------------------
# get_daily_usage
# ---------------------------------------------------------------------------

async def test_get_daily_usage_returns_0_when_no_records(mock_pool, mock_conn):
    """fetchrow returning {'cnt': 0} → get_daily_usage returns 0."""
    mock_conn.fetchrow = AsyncMock(return_value={"cnt": 0})
    result = await get_daily_usage(mock_pool, "claude-sonnet-4")
    assert result == 0


async def test_get_daily_usage_returns_count_from_db(mock_pool, mock_conn):
    """fetchrow returning {'cnt': 42} → get_daily_usage returns 42."""
    mock_conn.fetchrow = AsyncMock(return_value={"cnt": 42})
    result = await get_daily_usage(mock_pool, "claude-sonnet-4")
    assert result == 42


async def test_get_daily_usage_queries_correct_model(mock_pool, mock_conn):
    """The SQL query receives the model name as the first parameter."""
    mock_conn.fetchrow = AsyncMock(return_value={"cnt": 5})
    await get_daily_usage(mock_pool, "claude-haiku-3-5")
    call_args = mock_conn.fetchrow.call_args
    assert "claude-haiku-3-5" in call_args[0]


async def test_get_daily_usage_returns_0_when_row_is_none(mock_pool, mock_conn):
    """fetchrow returning None (no rows) → returns 0."""
    mock_conn.fetchrow = AsyncMock(return_value=None)
    result = await get_daily_usage(mock_pool, "claude-sonnet-4")
    assert result == 0


# ---------------------------------------------------------------------------
# check_model_budget
# ---------------------------------------------------------------------------

async def test_check_model_budget_available_below_soft_threshold(
    mock_pool, mock_conn, mocker
):
    """Usage at 50% of limit: available=True, warning=False."""
    limit = DAILY_LIMITS["openai/gpt-4.1"]  # 50
    used = int(limit * 0.50)
    mocker.patch(
        "pipeline.guardrails.get_daily_usage", new=AsyncMock(return_value=used)
    )

    result = await check_model_budget(mock_pool, "openai/gpt-4.1")

    assert result["available"] is True
    assert result["warning"] is False
    assert result["used"] == used
    assert result["limit"] == limit
    assert abs(result["pct"] - 50.0) < 1.0


async def test_check_model_budget_warning_above_soft_threshold(
    mock_pool, mocker
):
    """Usage at 82% of limit: available=True, warning=True."""
    limit = DAILY_LIMITS["openai/gpt-4.1"]
    used = int(limit * 0.82)
    mocker.patch(
        "pipeline.guardrails.get_daily_usage", new=AsyncMock(return_value=used)
    )

    result = await check_model_budget(mock_pool, "openai/gpt-4.1")

    assert result["available"] is True
    assert result["warning"] is True


async def test_check_model_budget_blocked_above_hard_threshold(
    mock_pool, mocker
):
    """Usage at 96% of limit: available=False (blocked)."""
    limit = DAILY_LIMITS["openai/gpt-4.1"]
    used = int(limit * 0.96)
    mocker.patch(
        "pipeline.guardrails.get_daily_usage", new=AsyncMock(return_value=used)
    )

    result = await check_model_budget(mock_pool, "openai/gpt-4.1")

    assert result["available"] is False


async def test_check_model_budget_exactly_at_hard_threshold_is_blocked(
    mock_pool, mocker
):
    """Usage exactly at HARD_THRESHOLD_PCT is blocked (< not <=)."""
    limit = DAILY_LIMITS["openai/gpt-4.1-mini"]
    # Use ceil to ensure the percentage is at or above the threshold
    import math
    used = math.ceil(limit * HARD_THRESHOLD_PCT / 100)
    mocker.patch(
        "pipeline.guardrails.get_daily_usage", new=AsyncMock(return_value=used)
    )

    result = await check_model_budget(mock_pool, "openai/gpt-4.1-mini")

    assert result["available"] is False


async def test_check_model_budget_unknown_model_is_always_available(mock_pool):
    """An unrecognised model name is allowed (no budget applies)."""
    result = await check_model_budget(mock_pool, "some-unknown-model-xyz")
    assert result["available"] is True
    assert result["warning"] is False
    assert result["limit"] == 0
    assert result["pct"] == 0.0


async def test_check_model_budget_returns_correct_model_field(
    mock_pool, mocker
):
    """The returned dict includes the model name."""
    mocker.patch(
        "pipeline.guardrails.get_daily_usage", new=AsyncMock(return_value=10)
    )
    result = await check_model_budget(mock_pool, "claude-sonnet-4")
    assert result["model"] == "claude-sonnet-4"


# ---------------------------------------------------------------------------
# log_model_call
# ---------------------------------------------------------------------------

async def test_log_model_call_executes_insert(mock_pool, mock_conn):
    """log_model_call inserts one row into rate_limit_log."""
    await log_model_call(
        mock_pool,
        model="claude-sonnet-4",
        tokens_in=500,
        tokens_out=200,
        run_id="run-abc",
        phase="research",
    )
    mock_conn.execute.assert_called_once()


async def test_log_model_call_includes_model_in_query(mock_pool, mock_conn):
    """The model name is passed as a positional argument to execute."""
    await log_model_call(mock_pool, model="claude-haiku-3-5")
    args = mock_conn.execute.call_args[0]
    assert "claude-haiku-3-5" in args


async def test_log_model_call_defaults_tokens_to_zero(mock_pool, mock_conn):
    """tokens_in and tokens_out default to 0 when not supplied."""
    await log_model_call(mock_pool, model="claude-sonnet-4")
    args = mock_conn.execute.call_args[0]
    # SQL + phase + model + tokens_in + tokens_out + run_id + request_type
    assert args[3] == 0  # tokens_in
    assert args[4] == 0  # tokens_out


async def test_log_model_call_passes_run_id_and_phase(mock_pool, mock_conn):
    """run_id and phase are forwarded to the INSERT statement."""
    await log_model_call(
        mock_pool, model="gpt-4o-mini", run_id="run-123", phase="writing"
    )
    args = mock_conn.execute.call_args[0]
    assert "run-123" in args
    assert "writing" in args
