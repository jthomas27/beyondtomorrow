"""
agents/tools/quality.py — Source credibility scoring tool

Scores a web domain's credibility on a scale of 1-5 based on domain type
and a curated tier list. Used by the Researcher agent to filter low-quality
sources from research outputs.
"""

from pipeline._sdk import function_tool

# Curated domain tiers (5 = highest credibility)
_TIER_5 = {
    # Government and international bodies
    "gov", "gov.uk", "gov.au", "europa.eu", "un.org", "who.int",
    "nih.gov", "nist.gov", "cdc.gov", "fda.gov", "whitehouse.gov",
    # Academic institutions
    "edu", "ac.uk", "ac.nz",
    # Peer-reviewed publishers
    "nature.com", "science.org", "cell.com", "pubmed.ncbi.nlm.nih.gov",
    "arxiv.org", "semanticscholar.org", "jstor.org", "springer.com",
    "sciencedirect.com", "wiley.com", "ieee.org",
}

_TIER_4 = {
    # Major news organisations with editorial standards
    "reuters.com", "bbc.com", "bbc.co.uk", "apnews.com",
    "economist.com", "ft.com", "nytimes.com", "washingtonpost.com",
    "theguardian.com", "foreignaffairs.com", "foreignpolicy.com",
    # Tech journalism
    "arstechnica.com", "spectrum.ieee.org", "wired.com", "techcrunch.com",
    "technologyreview.com",
    # International news
    "aljazeera.com", "dw.com", "france24.com",
}

_TIER_3 = {
    # Wikipedia (useful but requires verification)
    "wikipedia.org", "en.wikipedia.org",
    # Think tanks
    "brookings.edu", "rand.org", "csis.org", "chathamhouse.org",
    "cfr.org", "pewresearch.org",
    # Tech news
    "theregister.com", "zdnet.com", "infoq.com",
    # Dev communities
    "stackoverflow.com", "github.com", "dev.to",
}

_TIER_2 = {
    # General blogs and aggregators
    "medium.com", "substack.com", "wordpress.com", "blogspot.com",
    "reddit.com", "quora.com", "hackernews.com", "news.ycombinator.com",
    "linkedin.com",
}

# Tier 1 = everything else (unknown domains, personal blogs, etc.)


@function_tool
async def score_credibility(domain: str) -> str:
    """Score the credibility of a web domain on a scale of 1-5.

    Returns a score and a short explanation to help the Researcher decide
    whether to use the source.

    Score guide:
      5 = Government, academic, peer-reviewed — cite with confidence
      4 = Major news organisations with editorial standards — reliable
      3 = Think tanks, Wikipedia, established tech journalism — use with care
      2 = Blogs, aggregators, social platforms — low confidence, verify elsewhere
      1 = Unknown domain — verify before citing

    Args:
        domain: The domain to score (e.g. 'nist.gov', 'medium.com', 'arxiv.org').
    """
    # Normalise: strip www. and path components
    domain = domain.lower().removeprefix("www.").split("/")[0].strip()

    # Check suffix for gov/edu/ac domains
    tld = ".".join(domain.split(".")[-2:])  # e.g. "nist.gov", "mit.edu"
    tld_suffix = domain.split(".")[-1]      # e.g. "gov", "edu"

    if domain in _TIER_5 or tld in _TIER_5 or tld_suffix in {"gov", "edu"}:
        score = 5
        label = "Government / academic / peer-reviewed — high confidence"
    elif domain in _TIER_4 or tld in _TIER_4:
        score = 4
        label = "Major news organisation — reliable, editorial standards"
    elif domain in _TIER_3 or tld in _TIER_3:
        score = 3
        label = "Think tank / Wikipedia / established tech journalism — verify key claims"
    elif domain in _TIER_2 or tld in _TIER_2:
        score = 2
        label = "Blog / social platform — low confidence, verify elsewhere"
    else:
        score = 1
        label = "Unknown domain — treat with caution, verify before citing"

    return f"Credibility score: {score}/5 — {label} (domain: {domain})"
