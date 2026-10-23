"""Budget-aware routing using the configured chain; never override an unknown preference."""
from typing import Optional

from pipeline.config_loader import get_models
from pipeline.guardrails import check_model_budget

FALLBACK_CHAIN: list[str] = get_models()["fallback_chain"]


class ModelBudgetExceeded(RuntimeError):
    """No permitted model has capacity. Preserve work and defer the run."""


def get_fallback(model: str, *, allow_fallback: bool = True) -> Optional[str]:
    if not allow_fallback or model not in FALLBACK_CHAIN:
        return None
    idx = FALLBACK_CHAIN.index(model) + 1
    return FALLBACK_CHAIN[idx] if idx < len(FALLBACK_CHAIN) else None


async def select_model(preferred_model: str, pool=None, *, allow_fallback: bool = True) -> str:
    if pool is None:
        return preferred_model
    candidates = [preferred_model]
    if allow_fallback and preferred_model in FALLBACK_CHAIN:
        candidates = FALLBACK_CHAIN[FALLBACK_CHAIN.index(preferred_model):]
    for model in candidates:
        status = await check_model_budget(pool, model)
        if status["available"]:
            return model
    raise ModelBudgetExceeded(f"No permitted model has capacity for {preferred_model}; defer the run")
