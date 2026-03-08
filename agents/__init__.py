# agents/__init__.py
# Re-exports all openai-agents SDK symbols into this namespace so that:
#   from agents import Agent, function_tool, Runner, ...
# works correctly even though this directory shadows the SDK package.
#
# All app code lives in pipeline/. This agents/ package exists solely to:
#   1. Expose the SDK symbols (Agent, Runner, function_tool, etc.)
#   2. Keep agents/embeddings.py accessible

import sys as _sys
import os as _os

_THIS_DIR = _os.path.dirname(_os.path.abspath(__file__))


def _bootstrap_sdk():
    # Find the SDK in site-packages (a different agents/ dir than ours)
    _sdk_parent = None
    for _p in _sys.path:
        _resolved = _os.path.abspath(_p) if _p else _os.path.abspath(_os.getcwd())
        _cdir = _os.path.join(_resolved, "agents")
        if (
            _os.path.isfile(_os.path.join(_cdir, "__init__.py"))
            and _os.path.abspath(_cdir) != _THIS_DIR
        ):
            _sdk_parent = _resolved
            break
    if _sdk_parent is None:
        return  # SDK not installed — will fail later with a clear error

    # Temporarily add the SDK parent at the front of sys.path and remove
    # ourselves from the module cache so `import agents` finds the SDK.
    _sys.path.insert(0, _sdk_parent)
    _us = _sys.modules.pop("agents", None)
    try:
        import agents as _sdk
        _symbols = {k: v for k, v in vars(_sdk).items() if not k.startswith("__")}
    except ImportError:
        _symbols = {}
    finally:
        _sys.path.pop(0)
        if _us is not None:
            _sys.modules["agents"] = _us

    _mod = _sys.modules.get("agents")
    if _mod is not None:
        for _k, _v in _symbols.items():
            setattr(_mod, _k, _v)


_bootstrap_sdk()
del _bootstrap_sdk
