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


def test_approved_candidates_are_deduplicated_before_fetch_budget(mocker):
    from pipeline.tools.search import _approved_results
    mocker.patch("pipeline.tools.search._get_approved_domains", return_value={"noaa.gov", "nature.com"})
    results = _approved_results([
        {"href": "https://coast.noaa.gov/slr/?ref=one"},
        {"href": "https://coast.noaa.gov/slr/?ref=two"},
        {"href": "https://www.nature.com/articles/test?error=cookies_not_supported&code=opaque"},
        {"href": "https://unapproved.example/test"},
    ])
    assert [item["href"] for item in results] == ["https://coast.noaa.gov/slr/", "https://www.nature.com/articles/test"]


async def test_no_approved_sources_are_reported_as_filtering_not_extraction(mocker):
    from pipeline.tools.search import _search_and_index_impl
    mocker.patch("pipeline.tools.search._ddg_text", return_value=[{"href": "https://unapproved.example/test"}])
    mocker.patch("pipeline.tools.search._get_approved_domains", return_value={"nature.com"})
    mocker.patch("pipeline.tools.search.asyncio.sleep", new=AsyncMock())
    get_pool = mocker.patch("pipeline.db.get_pool", new=AsyncMock())
    result = await _search_and_index_impl("wet roads optics", 5)
    assert "source policy" in result and "site:" in result
    assert "no extractable" not in result
    get_pool.assert_not_awaited()


def test_pdf_evidence_is_extracted_as_pdf(mocker):
    import httpx
    from pipeline.tools.search import _extract_response_text
    page = MagicMock()
    page.extract_text.return_value = "A primary research paper"
    mocker.patch("pypdf.PdfReader", return_value=MagicMock(pages=[page]))
    response = httpx.Response(200, content=b"%PDF-test", headers={"content-type": "application/pdf"})
    assert _extract_response_text(response) == "A primary research paper"


# ---------------------------------------------------------------------------
# Helper — minimal HTTP response mock
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, text: str = "<html/>", status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.headers = {"content-type": "text/html"}
        self.content = text.encode()

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
        {"title": "AI Breakthrough 2024", "href": "https://science.org/ai", "body": "New advances in AI."},
        {"title": "Climate Tipping Points", "href": "https://nature.com/climate", "body": "Rapid climate shifts."},
    ]
    with patch("pipeline.tools.search.DDGS") as mock_cls:
        inst = MagicMock()
        inst.text.return_value = fake_results
        mock_cls.return_value.__enter__ = MagicMock(return_value=inst)
        mock_cls.return_value.__exit__ = MagicMock(return_value=False)

        result = await call_tool(web_search, query="AI climate", max_results=2)

    assert "AI Breakthrough 2024" in result
    assert "https://science.org/ai" in result
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

        result = await call_tool(fetch_page, url="https://nature.com/long-read")

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

        result = await call_tool(fetch_page, url="https://nature.com/page")

    assert "Failed to fetch" in result
    assert "https://nature.com/page" in result


@pytest.mark.asyncio
async def test_fetch_page_handles_empty_extraction():
    """When trafilatura returns None the tool should report extraction failure."""
    with patch("pipeline.tools.search.httpx.AsyncClient") as mock_cls, \
         patch("pipeline.tools.search.trafilatura.extract", return_value=None):

        mock_http = AsyncMock()
        mock_http.get = AsyncMock(return_value=_FakeResponse("<script>ads()</script>"))
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_http)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        result = await call_tool(fetch_page, url="https://nature.com/")

    assert "Could not extract text" in result
    assert "https://nature.com/" in result


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

    # Mock DB for corpus indexing (arXiv now stores abstracts)
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(side_effect=[42, 10])  # doc_id, chunk_id
    mock_conn.execute = AsyncMock()
    txn_cm = MagicMock()
    txn_cm.__aenter__ = AsyncMock(return_value=None)
    txn_cm.__aexit__ = AsyncMock(return_value=False)
    mock_conn.transaction = MagicMock(return_value=txn_cm)
    pool = MagicMock()
    acq_cm = MagicMock()
    acq_cm.__aenter__ = AsyncMock(return_value=mock_conn)
    acq_cm.__aexit__ = AsyncMock(return_value=False)
    pool.acquire = MagicMock(return_value=acq_cm)

    with patch.dict(sys.modules, {"arxiv": mock_arxiv}), \
         patch("pipeline.db.get_pool", AsyncMock(return_value=pool)), \
         patch("pipeline.embeddings.embed_batch", return_value=[[0.0] * 384]):
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


def test_search_retry_preserves_industry_date_and_site():
    from pipeline.tools.search import _query_variants
    variants = _query_variants("explore equity market sell off in technology stocks in October 2026 site:cnbc.com")
    for query in variants:
        assert all(term in query for term in ("technology", "stocks", "October", "2026", "site:cnbc.com"))


async def test_prefetch_preserves_event_context_and_uses_alternative_source(mocker):
    from pipeline.tools.search import _prefetch_topic
    mocker.patch("pipeline.tools.search._get_approved_domains", return_value={"nasdaq.com", "cnbc.com"})
    search = mocker.patch("pipeline.tools.search._search_and_index_impl", new=AsyncMock(return_value="Indexed"))
    mocker.patch("pipeline.tools.search.asyncio.sleep", new=AsyncMock())
    await _prefetch_topic("explore equity market sell off in technology stocks in October 2026", 2)
    queries = [call.args[0] for call in search.await_args_list]
    assert len(queries) == 2
    assert all(all(term in query for term in ("technology", "stocks", "October", "2026")) for query in queries)
    assert "site:" in queries[1]


def test_recovery_removes_old_site_filters_and_stays_bounded(mocker):
    from pipeline.tools.search import _recovery_queries
    mocker.patch("pipeline.tools.search._get_approved_domains", return_value={"nasdaq.com", "cnbc.com"})
    mocker.patch("pipeline.source_policy.ranked_sources", return_value=[{"domain": "nasdaq.com"}, {"domain": "cnbc.com"}])
    queries = _recovery_queries("October 2026 technology stocks site:reuters.com OR site:ft.com")
    assert len(queries) == 2
    assert all(query.count("site:") == 1 and "reuters.com" not in query and "ft.com" not in query for query in queries)


async def test_blocked_fetch_recovers_from_approved_alternative_without_snippets(mocker):
    from pipeline.tools.search import _search_and_index_impl
    mocker.patch("pipeline.tools.search._get_approved_domains", return_value={"reuters.com", "nasdaq.com", "cnbc.com"})
    mocker.patch("pipeline.source_policy.ranked_sources", return_value=[{"domain": "nasdaq.com"}, {"domain": "cnbc.com"}])
    def search(query, count):
        if "site:nasdaq.com" in query:
            return [{"href": "https://nasdaq.com/news/report", "title": "Dated exchange report"}]
        if "site:cnbc.com" in query:
            return []
        return [{"href": "https://reuters.com/markets/report", "title": "Blocked", "body": "Do not use snippet"}]
    mocker.patch("pipeline.tools.search._ddg_text", side_effect=search)
    mocker.patch("pipeline.tools.search.asyncio.sleep", new=AsyncMock())
    conn = AsyncMock()
    conn.fetch.side_effect = [[], [{"source": "https://nasdaq.com/news/report"}]]
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    pool = MagicMock()
    pool.acquire.return_value = cm
    mocker.patch("pipeline.db.get_pool", new=AsyncMock(return_value=pool))
    client = AsyncMock()
    client.get.return_value = _FakeResponse(status_code=403)
    cls = mocker.patch("pipeline.tools.search.httpx.AsyncClient")
    cls.return_value.__aenter__ = AsyncMock(return_value=client)
    cls.return_value.__aexit__ = AsyncMock(return_value=False)
    embed = mocker.patch("pipeline.embeddings.embed_batch")
    result = await _search_and_index_impl("October 2026 technology stocks", 2)
    assert "https://nasdaq.com/news/report" in result and "(cached)" in result
    assert "Do not use snippet" not in result
    client.get.assert_awaited_once()
    embed.assert_not_called()


async def test_search_backend_error_allows_next_variant(mocker):
    from pipeline.tools.search import _search_and_index_impl
    mocker.patch("pipeline.tools.search._get_approved_domains", return_value={"nature.com"})
    ddg = mocker.patch("pipeline.tools.search._ddg_text", side_effect=[RuntimeError("backend unavailable"), []])
    mocker.patch("pipeline.tools.search.asyncio.sleep", new=AsyncMock())
    result = await _search_and_index_impl("please investigate optics")
    assert "No approved web results" in result
    assert ddg.call_count == 2


# Source selection and publication evidence regression tests
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from pipeline.source_policy import (
    diversify, ranked_sources, require_article_evidence, require_research_evidence,
)


def test_candidates_follow_topic_and_avoid_unrelated_issuers():
    finance = [s["domain"] for s in ranked_sources("CoreWeave liabilities revenue debt financial distress")]
    climate = [s["domain"] for s in ranked_sources("climate carbon emissions warming")]
    assert "investors.coreweave.com" in finance[:3] and "sec.gov" in finance[:3]
    assert "investors.coreweave.com" not in climate
    assert "sec.gov" not in climate[:3]
    assert "cnbc.com" not in climate[:3]


def test_generic_article_words_do_not_select_unrelated_sources():
    assert ranked_sources("a beginners guide what you need to know") == []


def test_multiple_subdomains_do_not_count_as_independent_publishers():
    urls = ["https://www.cnbc.com/a", "https://cnbc.com/b", "https://reuters.com/c", "https://bbc.com/d"]
    assert diversify(urls, lambda u: u)[:3] == [urls[0], urls[2], urls[3]]


def test_approved_supported_research_passes(credible_research):
    require_research_evidence(json.dumps(credible_research))


def test_central_unanswered_question_becomes_a_disclosed_gap(credible_research):
    credible_research["question_coverage"][0]["status"] = "unanswered"
    result = require_research_evidence(json.dumps(credible_research))
    assert result["ready_to_write"] is True
    question = result["question_coverage"][0]
    assert question["status"] == "unanswered" and question["sources"] == []
    assert "A measured change" not in question["answer"]
    assert any("Unanswered evidence" in gap for gap in result["gaps"])


def test_sourced_partial_assessment_can_proceed_with_disclosed_gaps(credible_research):
    question = credible_research["question_coverage"][0]
    question.update(status="partial", requires_primary=True,
                    answer="Reported spending estimates exist, but paid AI demand is not separately disclosed.")
    credible_research["ready_to_write"] = False
    credible_research["gaps"] = ["Issuer AI-only revenue and utilisation are unavailable."]
    require_research_evidence(json.dumps(credible_research))
    require_article_evidence(
        "Spending remains uncertain. [Nature](https://nature.com/study) [NOAA](https://noaa.gov/data)",
        json.dumps(credible_research),
    )
    question["sources"] = []
    result = require_research_evidence(json.dumps(credible_research))
    assert result["question_coverage"][0]["status"] == "unanswered"


def test_partial_assessment_gets_a_gap_when_researcher_omits_it(credible_research):
    credible_research["question_coverage"][0]["status"] = "partial"
    credible_research["gaps"] = []
    result = require_research_evidence(json.dumps(credible_research))
    assert any("Partial evidence" in gap for gap in result["gaps"])


def test_missing_question_assessment_keeps_sourced_findings(credible_research):
    del credible_research["question_coverage"]
    result = require_research_evidence(json.dumps(credible_research))
    assert result["key_findings"]
    assert any("question coverage" in gap for gap in result["gaps"])


def test_single_publisher_findings_are_attributed_as_limited_corroboration(credible_research):
    credible_research["key_findings"][0]["sources"] = ["https://nature.com/study"]
    result = require_research_evidence(json.dumps(credible_research))
    assert any("one publisher" in gap for gap in result["gaps"])


def test_unapproved_sources_still_block(credible_research):
    credible_research["source_list"][1] = {"url": "https://unapproved.test/a", "credibility_score": 5}
    with pytest.raises(RuntimeError, match="unapproved or low-credibility"):
        require_research_evidence(json.dumps(credible_research))


def test_registry_credibility_overrides_researcher_scoring(credible_research):
    credible_research["source_list"][0]["credibility_score"] = 1
    result = require_research_evidence(json.dumps(credible_research))
    assert result["source_list"][0]["credibility_score"] == 5


def test_article_can_cite_one_approved_publisher(credible_research):
    single = "Evidence [Nature](https://nature.com/study)."
    require_article_evidence(single, json.dumps(credible_research))
    require_article_evidence(single + " And [NOAA](https://noaa.gov/data).", json.dumps(credible_research))


def test_article_cannot_introduce_unresearched_citation(credible_research):
    with pytest.raises(RuntimeError, match="approved research evidence"):
        require_article_evidence("[Other](https://nature.com/invented)", json.dumps(credible_research))


async def test_redirect_to_unapproved_site_is_never_requested():
    from pipeline.tools.search import _get_approved_page
    client = AsyncMock()
    client.get.return_value = httpx.Response(302, headers={"location": "https://unapproved.test/payload"})
    with pytest.raises(httpx.HTTPError, match="outside"):
        await _get_approved_page(client, "https://nature.com/study")
    client.get.assert_awaited_once_with("https://nature.com/study")


async def test_direct_fetch_refuses_unapproved_source_before_network(mocker):
    from pipeline.tools.search import fetch_page
    from tests.conftest import call_tool
    client = mocker.patch("pipeline.tools.search.httpx.AsyncClient")
    assert "Refused" in await call_tool(fetch_page, url="https://unapproved.test/a")
    client.assert_not_called()


def test_missing_allowlist_fails_closed(mocker):
    from pipeline.tools.search import _is_approved
    mocker.patch("pipeline.tools.search._get_approved_domains", return_value=set())
    assert not _is_approved("https://nature.com/study")


def test_existing_draft_cannot_skip_publication_gate(tmp_path, credible_research):
    from pipeline.main import _require_publish_evidence
    article = tmp_path / "topic-edited.md"
    article.write_text("[Nature](https://nature.com/study) [NOAA](https://noaa.gov/data)")
    with pytest.raises(RuntimeError, match="No research evidence"):
        _require_publish_evidence(article)
    cache = tmp_path / "topic-research.json"
    cache.write_text(json.dumps(credible_research))
    _require_publish_evidence(article)
    credible_research["ready_to_write"] = False
    cache.write_text(json.dumps(credible_research))
    _require_publish_evidence(article)


@pytest.mark.parametrize("topic", [
    "What does current financial reporting say about revenue?",
    "What do clinical studies say about health outcomes?",
    "What does the latest licensing policy permit?",
    "How do ocean currents influence climate?",
])
def test_one_source_policy_applies_to_all_topics(credible_research, topic):
    credible_research["source_list"] = credible_research["source_list"][:1]
    credible_research["key_findings"][0]["sources"] = ["https://nature.com/study"]
    question = credible_research["question_coverage"][0]
    question.update(question=topic, requires_primary=True, sources=["https://nature.com/study"])
    credible_research["ready_to_write"] = False
    result = require_research_evidence(json.dumps(credible_research))
    assert result["ready_to_write"] is True
    assert result["question_coverage"][0]["status"] == "partial"
    assert any("Primary evidence unavailable" in gap for gap in result["gaps"])
    require_article_evidence("[Nature](https://nature.com/study)", json.dumps(result))


def test_unsupported_findings_are_removed_before_drafting(credible_research):
    from pipeline.workflows.evidence import _require_research_evidence, _compact_research
    unsupported = "A fabricated factual claim"
    credible_research["key_findings"].append({"finding": unsupported, "sources": []})
    output = _require_research_evidence(json.dumps(credible_research))
    assert len(json.loads(output)["key_findings"]) == 1
    assert unsupported not in _compact_research(output, max_chars=8000)


def test_no_supported_findings_still_blocks(credible_research):
    credible_research["key_findings"][0]["sources"] = []
    with pytest.raises(RuntimeError, match="at least one finding"):
        require_research_evidence(json.dumps(credible_research))


@pytest.mark.parametrize("padding", ["<!-- [NOAA](https://noaa.gov/data) -->", "`[NOAA](https://noaa.gov/data)`", "![NOAA](https://noaa.gov/data)"])
def test_hidden_links_and_images_do_not_count_as_citations(credible_research, padding):
    with pytest.raises(RuntimeError, match="approved research evidence"):
        require_article_evidence(padding, json.dumps(credible_research))


async def test_publisher_tool_blocks_before_any_ghost_request(tmp_path, mocker):
    from pipeline.tools.ghost import publish_file_to_ghost
    from tests.conftest import call_tool
    mocker.patch("pipeline.tools.ghost._RESEARCH_DIR", tmp_path)
    (tmp_path / "article-edited.md").write_text("---\ntitle: An Article With No Supporting Research\n---\nBody")
    client = mocker.patch("pipeline.tools.ghost.httpx.AsyncClient")
    result = await call_tool(publish_file_to_ghost, filename="article-edited.md")
    assert result.startswith("Error: No research evidence")
    client.assert_not_called()
