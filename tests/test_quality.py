"""
tests/test_quality.py — Unit tests for pipeline/tools/quality.py

Covers:
    score_credibility  — returns correct 1-5 scores for each domain tier,
                         normalises www. prefixes, strips path components,
                         and formats the return string correctly.
"""

import pytest

from pipeline.tools.quality import score_credibility
from tests.conftest import call_tool


def _score(result: str) -> int:
    """Extract the integer score from 'Credibility score: N/5 — ...'."""
    return int(result.split("/")[0].split()[-1])


# ---------------------------------------------------------------------------
# Tier 5 — Government / academic / peer-reviewed (score = 5)
# ---------------------------------------------------------------------------

async def test_gov_tld_scores_5():
    """Any .gov TLD should score 5."""
    result = await call_tool(score_credibility, domain="whitehouse.gov")
    assert _score(result) == 5


async def test_gov_uk_domain_scores_5():
    """Specific gov.uk domains should score 5."""
    result = await call_tool(score_credibility, domain="nist.gov")
    assert _score(result) == 5


async def test_edu_tld_scores_5():
    """Any .edu TLD should score 5."""
    result = await call_tool(score_credibility, domain="mit.edu")
    assert _score(result) == 5


async def test_arxiv_uses_configured_preprint_score():
    """Preprints retain their configured score rather than a peer-reviewed tier."""
    result = await call_tool(score_credibility, domain="arxiv.org")
    assert _score(result) == 4


async def test_nature_scores_5():
    """nature.com (peer-reviewed) should score 5."""
    result = await call_tool(score_credibility, domain="nature.com")
    assert _score(result) == 5


async def test_pubmed_scores_5():
    """PubMed (government NIH, .gov host) should score 5."""
    result = await call_tool(
        score_credibility, domain="pubmed.ncbi.nlm.nih.gov"
    )
    assert _score(result) == 5


# ---------------------------------------------------------------------------
# Tier 4 — Major news organisations (score = 4)
# ---------------------------------------------------------------------------

async def test_reuters_scores_4():
    result = await call_tool(score_credibility, domain="reuters.com")
    assert _score(result) == 4


async def test_bbc_scores_4():
    result = await call_tool(score_credibility, domain="bbc.com")
    assert _score(result) == 4


async def test_arstechnica_uses_configured_score():
    result = await call_tool(score_credibility, domain="arstechnica.com")
    assert _score(result) == 3


# ---------------------------------------------------------------------------
# Tier 3 — Think tanks / Wikipedia / established tech journalism (score = 3)
# ---------------------------------------------------------------------------

async def test_wikipedia_scores_3():
    result = await call_tool(score_credibility, domain="wikipedia.org")
    assert _score(result) == 3


async def test_stackoverflow_scores_3():
    result = await call_tool(score_credibility, domain="stackoverflow.com")
    assert _score(result) == 3


async def test_brookings_configured_score_overrides_generic_edu_tld():
    """A specific configured score takes precedence over a generic TLD."""
    result = await call_tool(score_credibility, domain="brookings.edu")
    assert _score(result) == 4


async def test_rand_org_uses_configured_score():
    """The maintained source policy takes precedence over the legacy list."""
    result = await call_tool(score_credibility, domain="rand.org")
    assert _score(result) == 5


# ---------------------------------------------------------------------------
# Tier 2 — Blogs / aggregators / social platforms (score = 2)
# ---------------------------------------------------------------------------

async def test_medium_scores_2():
    result = await call_tool(score_credibility, domain="medium.com")
    assert _score(result) == 2


async def test_reddit_scores_2():
    result = await call_tool(score_credibility, domain="reddit.com")
    assert _score(result) == 2


async def test_linkedin_scores_2():
    result = await call_tool(score_credibility, domain="linkedin.com")
    assert _score(result) == 2


# ---------------------------------------------------------------------------
# Tier 1 — Unknown domain (score = 1)
# ---------------------------------------------------------------------------

async def test_unknown_domain_scores_1():
    result = await call_tool(
        score_credibility, domain="some-random-blog-xyz.io"
    )
    assert _score(result) == 1


async def test_personal_site_scores_1():
    result = await call_tool(score_credibility, domain="mysite.net")
    assert _score(result) == 1


# ---------------------------------------------------------------------------
# Domain normalisation
# ---------------------------------------------------------------------------

async def test_www_prefix_is_stripped():
    """www.reuters.com should score the same as reuters.com (tier 4)."""
    result = await call_tool(score_credibility, domain="www.reuters.com")
    assert _score(result) == 4


async def test_path_components_are_stripped():
    """Domain with path should still resolve correctly."""
    result = await call_tool(
        score_credibility, domain="reuters.com/technology/article"
    )
    assert _score(result) == 4


async def test_mixed_case_is_normalised():
    """Domain matching is case-insensitive."""
    result = await call_tool(score_credibility, domain="REUTERS.COM")
    assert _score(result) == 4


# ---------------------------------------------------------------------------
# Return format
# ---------------------------------------------------------------------------

async def test_return_format_contains_score_label_and_domain():
    """Result string always contains 'Credibility score:', '/5', and the domain."""
    result = await call_tool(score_credibility, domain="reuters.com")
    assert "Credibility score:" in result
    assert "/5" in result
    assert "reuters.com" in result


@pytest.mark.parametrize("domain,expected", [
    ("https://www.cnbc.com/2026/10/15/report.html", 4),
    ("dorseywright.nasdaq.com", 4),
    ("www.blackrock.com", 4),
    ("imf.org", 5),
    ("cnbc.com.untrusted.example", 1),
    ("https://cnbc.com@untrusted.example/report", 1),
])
async def test_configured_finance_scores_and_hostname_boundaries(domain, expected):
    result = await call_tool(score_credibility, domain=domain)
    assert _score(result) == expected
