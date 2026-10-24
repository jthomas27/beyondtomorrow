"""Agent workflow implementation."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from time import monotonic

from pipeline.paths import PROJECT_ROOT
from pipeline.workflows.common import _AGENT_TIMEOUT, _STAGE_COOLDOWN, _RETRY_BACKOFF_BASE

logger = logging.getLogger("pipeline")



async def _run_agent(task: str, model_override: str | None = None, debug: bool = False) -> None:
    """Initialise the SDK and run the orchestrator with the given task."""
    from pipeline._sdk import Runner
    from pipeline.setup import init_openai
    from pipeline.definitions import orchestrator
    from pipeline.db import close_pool

    init_openai()

    if model_override:
        from pipeline.definitions import model_settings_for
        orchestrator.model = model_override
        orchestrator.model_settings = model_settings_for("orchestrator", model_override=model_override)

    if debug:
        import sys as _sys
        _sdk_path = next(
            (p for p in _sys.path if "site-packages" in p and p != ""), None
        )
        if _sdk_path:
            _sys.path.insert(0, _sdk_path)
        try:
            from agents.tracing import set_tracing_export_api_enabled
            set_tracing_export_api_enabled(False)
        except ImportError:
            pass
        finally:
            if _sdk_path and _sys.path[0] == _sdk_path and "site-packages" in _sys.path[0]:
                _sys.path.pop(0)

    logger.info("Starting: %s", task)

    try:
        from pipeline.model_usage import ModelUsageHooks
        from pipeline.db import get_pool
        pool = await get_pool()
        result = await asyncio.wait_for(
            Runner.run(orchestrator, input=task, max_turns=30, hooks=ModelUsageHooks(pool)),
            timeout=_AGENT_TIMEOUT * 3,  # orchestrator may run multiple agents
        )
        logger.info("Complete")
        print(result.final_output)
    finally:
        await close_pool()
