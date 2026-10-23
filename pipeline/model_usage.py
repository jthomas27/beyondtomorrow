"""Record each completed model turn, including turns before a retry or tool failure."""
import logging

from agents.lifecycle import RunHooksBase

from pipeline.guardrails import check_model_budget, log_model_call

logger = logging.getLogger("pipeline.model_usage")


class ModelUsageHooks(RunHooksBase):
    def __init__(self, pool, run_log=None):
        self.pool = pool
        self.run_log = run_log

    async def on_llm_start(self, context, agent, system_prompt, input_items):
        if self.pool is None:
            return
        from pipeline.degradation import ModelBudgetExceeded

        status = await check_model_budget(self.pool, agent.model)
        if not status["available"]:
            raise ModelBudgetExceeded(f"Capacity exhausted for {agent.model}; defer the run")

    async def on_llm_end(self, context, agent, response):
        usage = response.usage
        tokens_in = usage.input_tokens or 0
        tokens_out = usage.output_tokens or 0
        cached = getattr(getattr(usage, "input_tokens_details", None), "cached_tokens", 0) or 0
        reasoning = getattr(getattr(usage, "output_tokens_details", None), "reasoning_tokens", 0) or 0
        logger.info(
            "Model turn: agent=%s model=%s input=%d output=%d cached=%d reasoning=%d",
            agent.name, agent.model, tokens_in, tokens_out, cached, reasoning,
        )
        if self.pool is not None:
            await log_model_call(
                self.pool, agent.model, tokens_in=tokens_in, tokens_out=tokens_out,
                run_id=getattr(self.run_log, "run_id", None), phase=agent.name.lower(),
            )
