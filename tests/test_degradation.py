"""Routing must preserve quality, explicit overrides, and hard budgets."""
from unittest.mock import AsyncMock
import pytest
from pipeline.config_loader import get_models
from pipeline.degradation import FALLBACK_CHAIN, ModelBudgetExceeded, get_fallback, select_model


def test_chain_uses_configuration():
    assert FALLBACK_CHAIN == get_models()["fallback_chain"]
    assert FALLBACK_CHAIN == ["gpt-6.1-sol", "gpt-6-luna"]


def test_fallback_is_explicit():
    assert get_fallback("gpt-6.1-sol") == "gpt-6-luna"
    assert get_fallback("gpt-6.1-sol", allow_fallback=False) is None
    assert get_fallback("gpt-6-luna") is None
    assert get_fallback("custom-model") is None


async def test_no_pool_keeps_preference():
    assert await select_model("custom-model") == "custom-model"


async def test_unknown_preference_is_not_replaced(mocker):
    check = mocker.patch("pipeline.degradation.check_model_budget", new=AsyncMock(return_value={"available": True}))
    assert await select_model("custom-model", pool=object()) == "custom-model"
    assert check.call_args.args[1] == "custom-model"


async def test_optional_fallback_when_primary_exhausted(mocker):
    mocker.patch("pipeline.degradation.check_model_budget", new=AsyncMock(side_effect=[{"available": False}, {"available": True}]))
    assert await select_model("gpt-6.1-sol", pool=object()) == "gpt-6-luna"


@pytest.mark.parametrize("model,allow", [("gpt-6.1-sol", False), ("gpt-6-luna", True), ("custom-model", True)])
async def test_exhaustion_defers_instead_of_bypassing_budget(mocker, model, allow):
    check = mocker.patch("pipeline.degradation.check_model_budget", new=AsyncMock(return_value={"available": False}))
    with pytest.raises(ModelBudgetExceeded):
        await select_model(model, pool=object(), allow_fallback=allow)
    check.assert_awaited_once()


async def test_all_fallbacks_exhausted_defers(mocker):
    mocker.patch("pipeline.degradation.check_model_budget", new=AsyncMock(return_value={"available": False}))
    with pytest.raises(ModelBudgetExceeded):
        await select_model("gpt-6.1-sol", pool=object())
