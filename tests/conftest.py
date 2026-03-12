"""
tests/conftest.py — Shared fixtures and helpers for the BeyondTomorrow.World
test suite.

Usage in test modules:
    from tests.conftest import call_tool

    result = await call_tool(web_search, query="climate", max_results=3)
"""

import json
import pytest


# ---------------------------------------------------------------------------
# Async tool invocation helper
# ---------------------------------------------------------------------------

class _ToolCtx:
    """Minimal stand-in for agents.run_context.ToolContext.

    FunctionTool.on_invoke_tool only reads ctx.tool_name at the start of the
    invocation chain, so providing just that attribute is sufficient.
    """

    def __init__(self, tool_name: str):
        self.tool_name = tool_name


async def call_tool(tool, **kwargs) -> str:
    """Invoke a @function_tool decorated object with keyword arguments.

    Constructs the minimal ToolContext the SDK requires and serialises kwargs
    to JSON, mirroring exactly what the agent runtime does.

    Example::

        result = await call_tool(web_search, query="AI news", max_results=3)
    """
    ctx = _ToolCtx(tool.name)
    return await tool.on_invoke_tool(ctx, json.dumps(kwargs))


# ---------------------------------------------------------------------------
# pytest-asyncio event-loop policy (re-use one loop per session)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Shared mock fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_conn(mocker):
    """Async mock for an asyncpg connection with transaction support.

    pool.acquire() and conn.transaction() must be regular MagicMock (not
    AsyncMock) so that calling them returns the context manager directly
    rather than a coroutine, which async-with cannot consume.
    """
    conn = mocker.AsyncMock()

    txn_cm = mocker.MagicMock()
    txn_cm.__aenter__ = mocker.AsyncMock(return_value=None)
    txn_cm.__aexit__ = mocker.AsyncMock(return_value=False)
    # Regular MagicMock — pool.transaction() returns the CM, not a coroutine
    conn.transaction = mocker.MagicMock(return_value=txn_cm)

    return conn


@pytest.fixture
def mock_pool(mocker, mock_conn):
    """Async mock for an asyncpg pool that yields mock_conn on acquire()."""
    pool = mocker.AsyncMock()

    acquire_cm = mocker.MagicMock()
    acquire_cm.__aenter__ = mocker.AsyncMock(return_value=mock_conn)
    acquire_cm.__aexit__ = mocker.AsyncMock(return_value=False)
    # Regular MagicMock — pool.acquire() returns the CM, not a coroutine
    pool.acquire = mocker.MagicMock(return_value=acquire_cm)

    return pool
