"""Regression cases from the October capex research failure; no live services."""
import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock

from pipeline.tools.search import _extract_response_text, _evidence_excerpt
from pipeline.tools.corpus import read_indexed_source, search_corpus
from pipeline.source_policy import ranked_sources
from tests.conftest import call_tool


def test_sec_submission_envelope_preserves_financial_table():
    html = '''<DOCUMENT><TYPE>EX-99.1<SEQUENCE>3<FILENAME>results.htm<TEXT>
    <html><body><h1>Quarterly results</h1><p>Our results for the quarter ended
    September 30 include investment in computing infrastructure.</p>
    <table><tr><th>Metric</th><th>2026</th><th>2025</th></tr>
    <tr><td>Capital expenditures</td><td>34000</td><td>21000</td></tr></table>
    <p>Capital expenditures include principal payments on finance leases.</p>
    </body></html></TEXT></DOCUMENT>'''
    text = _extract_response_text(httpx.Response(200, text=html, headers={"content-type": "text/html"}))
    assert "Capital expenditures" in text
    assert "34000" in text and "21000" in text


def test_relevant_late_filing_section_survives_excerpt_budget():
    text = "Annual report for 2026.\n" + "Unrelated introductory material.\n" * 1000
    text += "\nCapital expenditures for property and equipment totalled $34 billion.\n" * 5
    result = _evidence_excerpt(text, "capex", 2000)
    assert "Annual report for 2026" in result
    assert "$34 billion" in result
    assert "document abridged" in result
    assert len(result) <= 2000


def test_big_tech_aliases_surface_official_issuers_without_affecting_climate():
    candidates = {s["domain"] for s in ranked_sources("Big Tech capex plans")[:10]}
    assert {"atmeta.com", "microsoft.com", "aboutamazon.com", "abc.xyz"} <= candidates
    climate = {s["domain"] for s in ranked_sources("climate carbon emissions")}
    assert not {"atmeta.com", "aboutamazon.com", "abc.xyz"} & climate


def pool_for(conn):
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


async def test_exact_source_read_avoids_embedding_and_global_ranking(mocker):
    conn = AsyncMock()
    conn.fetchrow.return_value = {"title": "Issuer results", "source_type": "webpage",
                                 "content": "Verified revenue was $40 billion."}
    mocker.patch("pipeline.tools.corpus.get_pool", AsyncMock(return_value=pool_for(conn)))
    embed = mocker.patch("pipeline.tools.corpus.embed")
    url = "https://www.sec.gov/Archives/issuer/results.htm"
    result = await call_tool(read_indexed_source, url=url, query="revenue")
    assert "$40 billion" in result and url in result
    assert conn.fetchrow.call_args.args[1] == url
    embed.assert_not_called()


async def test_exact_source_read_rejects_unapproved_urls_before_database(mocker):
    pool = mocker.patch("pipeline.tools.corpus.get_pool", AsyncMock())
    result = await call_tool(read_indexed_source, url="https://unapproved.example/data")
    assert "approved external original" in result
    pool.assert_not_awaited()


@pytest.mark.parametrize("hybrid", [True, False])
async def test_evidence_filter_applies_before_limit_in_every_retrieval_path(mocker, hybrid):
    conn = AsyncMock()
    conn.fetchval.return_value = hybrid
    conn.fetch.return_value = []
    mocker.patch("pipeline.tools.corpus.get_pool", AsyncMock(return_value=pool_for(conn)))
    mocker.patch("pipeline.tools.corpus.embed", return_value=[0.0] * 1536)
    await call_tool(search_corpus, query="capital expenditure evidence", evidence_only=True)
    assert conn.fetch.call_count == 2  # vector + keyword/hybrid fallback
    for call in conn.fetch.call_args_list:
        sql = call.args[0]
        assert sql.index("NOT IN ('research', 'finding', 'subtopic')") < sql.index("LIMIT")
        assert "beyondtomorrow" in sql and "^https?://" in sql
