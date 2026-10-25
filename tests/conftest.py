"""
tests/conftest.py — Shared fixtures and helpers for the BeyondTomorrow.World
test suite.

Usage in test modules:
    from tests.conftest import call_tool

    result = await call_tool(web_search, query="climate", max_results=3)
"""

import json
import pytest


@pytest.fixture
def credible_research():
    return {
        "source_list": [{"url": url, "credibility_score": 4} for url in
                        ["https://nature.com/study", "https://noaa.gov/data", "https://reuters.com/report"]],
        "key_findings": [{"finding": "A supported comparison", "confidence": "medium",
                          "sources": ["https://nature.com/study", "https://noaa.gov/data"]}],
        "question_coverage": [{"question": "What do the measurements show?", "essential": True,
                               "status": "answered", "answer": "A measured change",
                               "sources": ["https://nature.com/study", "https://noaa.gov/data"]}],
        "ready_to_write": True,
    }


@pytest.fixture(autouse=True)
def block_accidental_unit_test_http(request, monkeypatch):
    """Unit tests must not send real requests when an expected mock is missing."""
    if request.node.get_closest_marker("integration"):
        return
    import httpx

    def blocked(self, request):
        raise httpx.ConnectError("Live HTTP disabled in unit tests", request=request)

    async def async_blocked(self, request):
        raise httpx.ConnectError("Live HTTP disabled in unit tests", request=request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_blocked)
    import asyncpg
    async def blocked_database(*args, **kwargs):
        raise RuntimeError('Live PostgreSQL disabled in unit tests; mock the database boundary')
    monkeypatch.setattr(asyncpg, 'connect', blocked_database)
    monkeypatch.setattr(asyncpg, 'create_pool', blocked_database)


@pytest.fixture
def memory_deliveries(monkeypatch):
    """Explicit offline ledger stand-in for provider tests; state survives retries."""
    from contextlib import asynccontextmanager
    from datetime import datetime, timezone
    records = {}
    class Receipt:
        status = 'pending'
        external_id = None
        data = None
        updated_at = datetime.now(timezone.utc)
        async def save(self, status, external_id=None, data=None):
            self.status, self.external_id = status, external_id
            if data is not None:
                self.data = data
    @asynccontextmanager
    async def delivery(channel, article, recipient=''):
        key = (channel, article, recipient)
        if key not in records:
            records[key] = Receipt()
            records[key].data = {}
        yield records[key]
    monkeypatch.setattr('pipeline.storage.deliveries.delivery_record', delivery)
    return records


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
