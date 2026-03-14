"""
agents/setup.py — SDK initialisation using GitHub Models API

Call init_github_models() once at startup (from agents/main.py or wherever
the agent runner is invoked). After that, all Agent definitions in
agents/definitions.py will use this client automatically.

Required env var:
    GITHUB_TOKEN — Fine-grained PAT with models:read scope
"""

import os
from openai import AsyncOpenAI
from pipeline._sdk import set_default_openai_client, set_default_openai_api


def init_github_models() -> AsyncOpenAI:
    """Configure the OpenAI Agents SDK to use GitHub Models API.

    Returns the AsyncOpenAI client so callers can inspect it if needed.
    Raises RuntimeError if GITHUB_TOKEN is not set.
    """
    # Disable the SDK's built-in trace exporter. It tries to POST to
    # https://api.openai.com/v1/traces using OPENAI_API_KEY, which is not set
    # on this project (we use GITHUB_TOKEN for GitHub Models). Without this,
    # every pipeline run logs "[non-fatal] Tracing client error 401" repeatedly.
    try:
        from agents.tracing import set_tracing_export_api_enabled
        set_tracing_export_api_enabled(False)
    except ImportError:
        pass

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN environment variable is not set. "
            "Create a fine-grained GitHub PAT with 'models:read' scope "
            "and set it in your Railway environment variables."
        )

    client = AsyncOpenAI(
        base_url="https://models.github.ai/inference",
        api_key=token,
    )
    set_default_openai_client(client)
    set_default_openai_api("chat_completions")
    return client
