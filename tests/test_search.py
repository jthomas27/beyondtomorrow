"""
tests/test_search.py — Unit tests for pipeline/tools/search.py

Covers:
    web_search   — DuckDuckGo text search
    fetch_page   — HTTP fetch + trafilatura extraction
    search_arxiv — arXiv academic paper search

All network calls are mocked; no internet access is required.
"""

import sys
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from pipeline.tools.search import web_search, fetch_page, search_arxiv
from tests.conftest import call_tool


# ---------------------------------------------------------------------------
# Helper — minimal HTTP response mock
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, text: str = "<html/>", status_code: int = 200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=MagicMock(),
                response=MagicMock(status_code=self.status_code),
            )


# ---------------------------------------------------------------------------
# web_search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_web_search_returns_formatted_results():
    """Results should include title, URL, and snippet for each hit."""
    fake_results = [
        {"title": "AI Breakthrough 2024", "href": "https://example.com/ai", "body": "New advances in AI."},
        {"title": "Climate Tipping Points", "href": "https://nature.com/climate", "body": "Rapid climate shifts."},
    ]
    with patch("pipeline.tools.search.DDGS") as mock_cls:
        inst = MagicMock()
        inst.text.return_value = fake_results
        mock_cls.return_value.__enter__ = MagicMock(return_value=inst)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = await call_tool(web_search, query="AI climate", max_results=2)

    assert "AI Breakthrough 2024" in result
    assert "https://example.com/ai" in result
    assert "New advances in AI." in result
    assert "Climate Tipping Points" in result
    assert "https://nature.com/climate" in result


@pytest.mark.asyncio
async def test_web_search_no_results_returns_informative_message():
    """Empty DDGS response should produce a 'No results' message with the query."""
    with patch("pipeline.tools.search.DDGS") as mock_cls:
        inst = MagicMock()
        inst.text.return_value = []
        mock_cls.return_value.__enter__ = MagicMock(return_value=inst)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = await call_tool(web_search, query="xyzzy_nonexistent_42", max_results=5)

    assert "No results found" in result
    assert "xyzzy_nonexistent_42" in result


@pytest.mark.asyncio
async def test_web_search_forwards_max_results_to_ddgs():
    """max_results must be forwarded verbatim to DDGS.text()."""
    with patch("pipeline.tools.search.DDGS") as mock_cls:
        inst = MagicMock()
        inst.text.return_value = [{"title": "T", "href": "https://t.co", "body": "b"}]
        mock_cls.return_value.__enter__ = MagicMock(return_value=inst)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        await call_tool(web_search, query="test query", max_results=7)

    inst.text.assert_called_once_with("test query", max_results=7)


# ---------------------------------------------------------------------------
# fetch_page
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_page_extracts_article_text():
    """Extracted text and source URL should both appear in the output."""
    extracted = "The oceans are warming at an unprecedented rate."
    with patch("pipeline.tools.search.httpx.AsyncClient") as mock_cls, \
         patch("pipeline.tools.search.trafilatura.extract", return_value=extracted):

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=_FakeResponse("<html><p>…</p></html>"))
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await call_tool(fetch_page, url="https://nature.com/article/123")

    assert extracted in result
    assert "https://nature.com/article/123" in result


@pytest.mark.asyncio
async def test_fetch_page_truncates_long_content():
    """Content longer than 16 000 chars must be cut and marked '[... truncated]'."""
    long_text = "X" * 20_000
    with patch("pipeline.tools.search.httpx.AsyncClient") as mock_cls, \
         patch("pipeline.tools.search.trafilatura.extract", return_value=long_text):

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=_FakeResponse())
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await call_tool(fetch_page, url="https://example.com/long-read")

    assert "[... truncated]" in result
    # Content portion should not exceed the limit by more than a small header overhead
    content_start = result.find("\n\n") + 2
    assert len(result[content_start:]) <= 16_100


@pytest.mark.asyncio
async def test_fetch_page_returns_error_on_http_failure():
    """An HTTP error (e.g. connection refused) must be gracefully reported."""
    import httpx
    with patch("pipeline.tools.search.httpx.AsyncClient") as mock_cls:
        mock_http = AsyncMock()
        mock_http.get = AsyncMock(side_effect=httpx.HTTPError("Connection refused"))
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await call_tool(fetch_page, url="https://down.example.com/page")

    assert "Failed to fetch" in result
    assert "https://down.example.com/page" in result


@pytest.mark.asyncio
async def test_fetch_page_handles_empty_extraction():
    """When trafilatura returns None the tool should report extraction failure."""
    with patch("pipeline.tools.search.httpx.AsyncClient") as mock_cls, \
         patch("pipeline.tools.search.trafilatura.extract", return_value=None):

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=_FakeResponse("<script>ads()</script>"))
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await call_tool(fetch_page, url="https://adspam.example.com/")

    assert "Could not extract text" in result
    assert "https://adspam.example.com/" in result


# ---------------------------------------------------------------------------
# search_arxiv
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_arxiv_returns_formatted_papers():
    """Results should include title, URL, publication date, and abstract snippet."""
    from datetime import datetime

    fake_paper = MagicMock()
    fake_paper.title = "Quantum Machine Learning Survey"
    fake_paper.entry_id = "https://arxiv.org/abs/2401.00001"
    fake_paper.published = datetime(2024, 3, 1)
    fake_paper.summary = ("We survey quantum machine learning algorithms. " * 20)

    mock_arxiv = MagicMock()
    mock_arxiv.Client.return_value.results.return_value = [fake_paper]

    with patch.dict(sys.modules, {"arxiv": mock_arxiv}):
        result = await call_tool(search_arxiv, query="quantum ML", max_results=3)

    assert "Quantum Machine Learning Survey" in result
    assert "https://arxiv.org/abs/2401.00001" in result
    assert "2024-03-01" in result
    # Abstract should be truncated at 500 chars
    assert len(result) < 5_000


@pytest.mark.asyncio
async def test_search_arxiv_no_results():
    """Empty arXiv response should produce a 'No arXiv results' message."""
    mock_arxiv = MagicMock()
    mock_arxiv.Client.return_value.results.return_value = []

    with patch.dict(sys.modules, {"arxiv": mock_arxiv}):
        result = await call_tool(search_arxiv, query="zzz_nothing_here", max_results=5)

    assert "No arXiv results" in result
