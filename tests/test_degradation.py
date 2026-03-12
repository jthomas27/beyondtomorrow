"""
tests/test_degradation.py — Unit tests for pipeline/degradation.py

Covers:
    get_fallback    — returns the next model in the chain, None at end,
                      first chain entry for unknown models
    select_model    — returns preferred model when pool is None (dry-run),
                      returns preferred when it is available,
                      falls back when preferred is exhausted,
                      returns last resort when all models exhausted
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from pipeline.degradation import (
    FALLBACK_CHAIN,
    get_fallback,
    select_model,
)


# ---------------------------------------------------------------------------
# get_fallback
# ---------------------------------------------------------------------------

def test_get_fallback_returns_next_in_chain():
    """Each model returns the next one in FALLBACK_CHAIN."""
    for i, model in enumerate(FALLBACK_CHAIN[:-1]):
        assert get_fallback(model) == FALLBACK_CHAIN[i + 1]


def test_get_fallback_returns_none_for_last_model():
    """The final model in the chain has no fallback → None."""
    last = FALLBACK_CHAIN[-1]
    assert get_fallback(last) is None


def test_get_fallback_returns_first_for_unknown_model():
    """An unknown model returns the first entry in the chain."""
    result = get_fallback("some-unknown-model-xyz")
    assert result == FALLBACK_CHAIN[0]


def test_get_fallback_chain_starts_with_opus():
    """The chain must start with the most capable model."""
    assert FALLBACK_CHAIN[0] == "claude-opus-4-6"


def test_get_fallback_chain_ends_with_cheap_model():
    """The chain must end with a high-volume / low-cost model."""
    assert FALLBACK_CHAIN[-1] == "gpt-4o-mini"


def test_get_fallback_sonnet_returns_haiku():
    """claude-sonnet-4 falls back to claude-haiku-3-5."""
    assert get_fallback("claude-sonnet-4") == "claude-haiku-3-5"


# ---------------------------------------------------------------------------
# select_model
# ---------------------------------------------------------------------------

async def test_select_model_returns_preferred_when_pool_is_none():
    """Without a pool (dry-run mode), the preferred model is returned as-is."""
    result = await select_model("claude-sonnet-4", pool=None)
    assert result == "claude-sonnet-4"


async def test_select_model_returns_preferred_when_available(mocker):
    """When the preferred model has budget remaining, it is returned."""
    mocker.patch(
        "pipeline.degradation.check_model_budget",
        new=AsyncMock(
            return_value={"available": True, "warning": False, "pct": 30.0}
        ),
    )
    result = await select_model("claude-sonnet-4", pool=object())
    assert result == "claude-sonnet-4"


async def test_select_model_falls_back_when_preferred_exhausted(mocker):
    """When preferred is exhausted the next available model is returned."""

    async def mock_check(pool, model):
        if model == "claude-sonnet-4":
            return {"available": False, "warning": True, "pct": 97.0}
        return {"available": True, "warning": False, "pct": 10.0}

    mocker.patch("pipeline.degradation.check_model_budget", side_effect=mock_check)
    result = await select_model("claude-sonnet-4", pool=object())
    assert result == "claude-haiku-3-5"


async def test_select_model_skips_multiple_exhausted_models(mocker):
    """Falls back past multiple exhausted models to find the first available."""
    exhausted = {"claude-opus-4-6", "claude-sonnet-4", "claude-haiku-3-5"}

    async def mock_check(pool, model):
        return {
            "available": model not in exhausted,
            "warning": False,
            "pct": 97.0 if model in exhausted else 10.0,
        }

    mocker.patch("pipeline.degradation.check_model_budget", side_effect=mock_check)
    result = await select_model("claude-opus-4-6", pool=object())
    assert result == "gpt-4o-mini"


async def test_select_model_returns_last_resort_when_all_exhausted(mocker):
    """When all models are exhausted returns the last entry (last resort)."""
    mocker.patch(
        "pipeline.degradation.check_model_budget",
        new=AsyncMock(
            return_value={"available": False, "warning": True, "pct": 99.0}
        ),
    )
    result = await select_model("claude-opus-4-6", pool=object())
    assert result == FALLBACK_CHAIN[-1]


async def test_select_model_starts_at_preferred_not_chain_start(mocker):
    """Selecting from an mid-chain model does not check models before it."""
    checked_models: list[str] = []

    async def mock_check(pool, model):
        checked_models.append(model)
        return {"available": True, "warning": False, "pct": 10.0}

    mocker.patch("pipeline.degradation.check_model_budget", side_effect=mock_check)
    await select_model("claude-haiku-3-5", pool=object())

    # Should only check haiku (and possibly gpt-4o-mini), not opus or sonnet
    for model in checked_models:
        idx_checked = FALLBACK_CHAIN.index(model) if model in FALLBACK_CHAIN else -1
        idx_haiku = FALLBACK_CHAIN.index("claude-haiku-3-5")
        assert idx_checked >= idx_haiku


async def test_select_model_with_unknown_preferred_defaults_to_opus(mocker):
    """An unknown preferred model triggers checking from the chain start."""
    checked_models: list[str] = []

    async def mock_check(pool, model):
        checked_models.append(model)
        return {"available": True, "warning": False, "pct": 5.0}

    mocker.patch("pipeline.degradation.check_model_budget", side_effect=mock_check)
    result = await select_model("some-unknown-model", pool=object())
    # Should start from beginning of chain
    assert result == FALLBACK_CHAIN[0]
