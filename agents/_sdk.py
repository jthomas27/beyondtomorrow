"""
agents/_sdk.py — Bridge module that loads the openai-agents SDK.

The local agents/ package shadows the installed 'openai-agents' SDK because
Python finds the local directory first in sys.path. This module bypasses that
by temporarily manipulating sys.path/sys.modules to load the SDK directly
from site-packages, then re-exports the symbols our code needs.

Usage in all agent modules:
    from agents._sdk import Agent, function_tool, Runner, ModelSettings
    from agents._sdk import set_default_openai_client, set_default_openai_api
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys

_THIS_PKG_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_openai_agents_sdk():
    """Load the openai-agents SDK from site-packages, bypassing the local package."""
    # Find the SDK's __init__.py in site-packages
    sdk_init = None
    for base in sys.path:
        if not base:
            # '' means current working directory — resolve it
            resolved = os.path.abspath(os.getcwd())
        else:
            resolved = os.path.abspath(base)

        candidate = os.path.join(resolved, "agents", "__init__.py")
        if os.path.isfile(candidate) and os.path.abspath(os.path.dirname(candidate)) != _THIS_PKG_DIR:
            sdk_init = candidate
            break

    if sdk_init is None:
        raise ImportError(
            "openai-agents SDK not found in site-packages. "
            "Run: pip install openai-agents"
        )

    sdk_dir = os.path.dirname(sdk_init)

    # Temporarily patch sys.modules: remove local 'agents' package entries
    # so the SDK's internal imports don't recurse into our local package.
    saved_modules = {}
    for key in list(sys.modules):
        if key == "agents" or key.startswith("agents."):
            saved_modules[key] = sys.modules.pop(key)

    # Add the SDK directory's parent to sys.path BEFORE the project root
    sdk_parent = os.path.dirname(sdk_dir)
    sys.path.insert(0, sdk_parent)

    try:
        import agents as _sdk_module  # noqa: F401 — loads from site-packages now

        # Pre-import the SDK submodules we need so they're cached as 'agents.xxx'
        for sub in ("run", "model_settings", "function_tool", "_openai_utils"):
            _sub_path = os.path.join(sdk_dir, sub.replace(".", os.sep) + ".py")
            if os.path.isfile(_sub_path):
                importlib.import_module(f"agents.{sub}")

        return sys.modules["agents"]

    finally:
        # Restore sys.path
        sys.path.remove(sdk_parent)
        # Restore our local modules.  The import above sets sys.modules["agents"]
        # to the SDK package, which would make project submodules (agents.setup,
        # agents.definitions, etc.) invisible.  Always restore the saved project
        # "agents" entry; for other keys only restore if not already present.
        if "agents" in saved_modules:
            sys.modules["agents"] = saved_modules["agents"]
        for key, mod in saved_modules.items():
            if key != "agents" and key not in sys.modules:
                sys.modules[key] = mod


_sdk = _load_openai_agents_sdk()

# Re-export what our code needs
Agent = _sdk.Agent
ModelSettings = _sdk.ModelSettings
function_tool = _sdk.function_tool
Runner = _sdk.Runner
set_default_openai_client = _sdk.set_default_openai_client
set_default_openai_api = _sdk.set_default_openai_api

__all__ = [
    "Agent",
    "ModelSettings",
    "function_tool",
    "Runner",
    "set_default_openai_client",
    "set_default_openai_api",
]
