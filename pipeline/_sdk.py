"""
pipeline/_sdk.py — Re-exports symbols from the openai-agents SDK.

The installed 'openai-agents' package registers itself as the 'agents' module.
Since our local code lives in 'pipeline/', there is no name clash and we can
import the SDK directly.

Usage in all pipeline modules:
    from pipeline._sdk import Agent, function_tool, Runner, ModelSettings
    from pipeline._sdk import set_default_openai_client, set_default_openai_api
"""

from agents import (  # noqa: F401  — this is the openai-agents SDK
    Agent,
    ModelSettings,
    function_tool,
    Runner,
    set_default_openai_client,
    set_default_openai_api,
)

__all__ = [
    "Agent",
    "ModelSettings",
    "function_tool",
    "Runner",
    "set_default_openai_client",
    "set_default_openai_api",
]
