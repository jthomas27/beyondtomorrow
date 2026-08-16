"""
pipeline/setup.py — SDK initialisation using OpenAI API

Call init_openai() once at startup (from pipeline/main.py or wherever
the agent runner is invoked). After that, all Agent definitions in
pipeline/definitions.py will use this client automatically.

Required env var:
    OPENAI_API_KEY — OpenAI platform API key (sk-...)
"""

import os
from openai import AsyncOpenAI
from pipeline._sdk import set_default_openai_client, set_default_openai_api


def init_openai() -> AsyncOpenAI:
    """Configure the OpenAI Agents SDK to use the OpenAI API directly.

    Returns the AsyncOpenAI client so callers can inspect it if needed.
    Raises RuntimeError if OPENAI_API_KEY is not set.
    """
    try:
        from agents.tracing import set_tracing_export_api_enabled
        set_tracing_export_api_enabled(False)
    except ImportError:
        pass

    token = os.environ.get("OPENAI_API_KEY")
    if not token:
        raise RuntimeError(
            "OPENAI_API_KEY environment variable is not set. "
            "Create an API key at https://platform.openai.com/api-keys "
            "and set it in your .env and Railway environment variables."
        )

    client = AsyncOpenAI(
        base_url="https://api.openai.com/v1",
        api_key=token,
    )
    set_default_openai_client(client)
    set_default_openai_api("chat_completions")
    return client


# Backward-compat alias so existing callers (init_github_models) still work
# during any incremental rollout.  Remove once all call sites are updated.
init_github_models = init_openai
